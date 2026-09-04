#!/usr/bin/env node
'use strict';
/**
 * Migra as imagens dos produtos Bagy/Dooca para produtos ja existentes no Shopify,
 * redimensionando automaticamente o que estourar o limite de 20 megapixels.
 *
 * Estrategia (rapida e a prova de falha):
 *   1) tenta enviar pela URL original  -> Shopify baixa sozinho, custo zero de banda
 *   2) se der 422 (limite de pixels)   -> baixa, reduz com sharp e envia em base64
 *
 * Uso:
 *   node migrar-imagens.js --fonte=bagy
 *   node migrar-imagens.js --fonte=csv --arquivo=imagens.csv
 *   node migrar-imagens.js --fonte=bagy --dry-run --limite=5
 *
 * Flags:
 *   --fonte=bagy|csv     de onde vem a lista de imagens (padrao: bagy)
 *   --arquivo=<path>     CSV de entrada (modo csv)
 *   --dry-run            simula, nao escreve nada no Shopify
 *   --limite=N           processa apenas N produtos (util para teste)
 *   --forcar             envia mesmo em produtos que ja tem imagem
 *   --chave=sku|handle   campo usado para casar Bagy x Shopify (padrao: sku)
 */

const fs = require('fs');
const L = require('./lib');

const args = Object.fromEntries(
  process.argv.slice(2).map((a) => {
    const m = a.match(/^--([^=]+)(?:=(.*))?$/);
    return m ? [m[1], m[2] === undefined ? true : m[2]] : [a, true];
  })
);

const cfg = L.lerConfig();
const DRY = !!args['dry-run'];
const FORCAR = !!args.forcar;
const CHAVE = args.chave === 'handle' ? 'handle' : 'sku';
const LIMITE = args.limite ? Number(args.limite) : Infinity;
const limitador = new L.Limitador(cfg.porSegundo);

// ------------------------------------------------------------- entrada ----

/** Coleta recursivamente qualquer URL de imagem dentro do objeto do produto. */
function urlsDeImagem(objeto, encontradas = []) {
  if (!objeto) return encontradas;
  if (typeof objeto === 'string') {
    if (/^https?:\/\/\S+\.(jpe?g|png|webp|gif|avif)(\?|$)/i.test(objeto)) encontradas.push(objeto);
    else if (cfg.cdnBase && /^[\w./-]+\.(jpe?g|png|webp|gif|avif)$/i.test(objeto)) {
      encontradas.push(`${cfg.cdnBase}/${objeto.replace(/^\/+/, '')}`);
    }
    return encontradas;
  }
  if (Array.isArray(objeto)) { objeto.forEach((v) => urlsDeImagem(v, encontradas)); return encontradas; }
  if (typeof objeto === 'object') {
    for (const [k, v] of Object.entries(objeto)) {
      // ignora campos que costumam guardar thumbs minusculas ou icones
      if (/^(icon|favicon|logo)$/i.test(k)) continue;
      urlsDeImagem(v, encontradas);
    }
  }
  return encontradas;
}

function skusDoProdutoBagy(p) {
  const chaves = [];
  const push = (v) => { if (v && String(v).trim()) chaves.push(String(v).trim()); };
  push(p.sku);
  push(p.reference);
  for (const v of p.variations || p.variants || []) { push(v.sku); push(v.reference); }
  return chaves;
}

async function lerProdutosBagy() {
  if (!cfg.bagyToken) throw new Error('BAGY_TOKEN nao configurado (.env). Use --fonte=csv se preferir importar de planilha.');
  const produtos = [];
  let pagina = 1;
  for (;;) {
    const url = `${cfg.bagyApi}/products?limit=100&page=${pagina}`;
    const resp = await fetch(url, {
      headers: { Authorization: `Bearer ${cfg.bagyToken}`, Accept: 'application/json' },
    });
    if (!resp.ok) throw new Error(`Bagy respondeu HTTP ${resp.status} em ${url}: ${(await resp.text()).slice(0, 300)}`);
    const json = await resp.json();
    const lote = Array.isArray(json) ? json : json.data || [];
    produtos.push(...lote);
    process.stdout.write(`\r  Bagy: ${produtos.length} produtos lidos...`);
    if (lote.length === 0) break;
    const meta = json.meta || {};
    if (meta.last_page && pagina >= meta.last_page) break;
    if (!meta.last_page && lote.length < 100) break;
    pagina += 1;
  }
  process.stdout.write('\n');
  return produtos.map((p) => ({
    id: p.id,
    nome: p.name || p.title || '',
    handle: p.slug || p.handle || '',
    skus: skusDoProdutoBagy(p),
    imagens: [...new Set(urlsDeImagem(p))],
  }));
}

function separarCSV(linha) {
  const campos = [];
  let atual = '', aspas = false;
  for (let i = 0; i < linha.length; i++) {
    const c = linha[i];
    if (aspas) {
      if (c === '"' && linha[i + 1] === '"') { atual += '"'; i++; }
      else if (c === '"') aspas = false;
      else atual += c;
    } else if (c === '"') aspas = true;
    else if (c === ',' || c === ';') { campos.push(atual); atual = ''; }
    else atual += c;
  }
  campos.push(atual);
  return campos.map((s) => s.trim());
}

/** CSV com colunas: sku (ou handle) e image_url (ou url/src). Uma linha por imagem. */
function lerProdutosCSV(arquivo) {
  const linhas = fs.readFileSync(arquivo, 'utf8').split(/\r?\n/).filter((l) => l.trim());
  if (!linhas.length) throw new Error(`CSV vazio: ${arquivo}`);
  const cab = separarCSV(linhas[0]).map((h) => h.toLowerCase());
  const iSku = cab.findIndex((h) => /^(sku|codigo|c[oó]digo)$/.test(h));
  const iHandle = cab.findIndex((h) => /^(handle|slug)$/.test(h));
  const iUrl = cab.findIndex((h) => /(image_url|imagem|image|url|src|foto)/.test(h));
  if (iUrl < 0) throw new Error('CSV precisa de uma coluna de URL da imagem (image_url / url / src).');
  if (iSku < 0 && iHandle < 0) throw new Error('CSV precisa de uma coluna sku ou handle.');

  const porChave = new Map();
  for (const linha of linhas.slice(1)) {
    const c = separarCSV(linha);
    const url = c[iUrl];
    if (!url) continue;
    const sku = iSku >= 0 ? c[iSku] : '';
    const handle = iHandle >= 0 ? c[iHandle] : '';
    const chave = (sku || handle).toLowerCase();
    if (!chave) continue;
    if (!porChave.has(chave)) {
      porChave.set(chave, { id: chave, nome: '', handle, skus: sku ? [sku] : [], imagens: [] });
    }
    porChave.get(chave).imagens.push(url);
  }
  return [...porChave.values()];
}

// -------------------------------------------------------------- Shopify ---

const normalizar = (v) => String(v || '').trim().toLowerCase();

async function indexarShopify() {
  const porSku = new Map();
  const porHandle = new Map();
  let total = 0;
  for await (const p of L.listarProdutosShopify(cfg, limitador)) {
    total++;
    porHandle.set(normalizar(p.handle), p);
    for (const v of p.variants || []) {
      const s = normalizar(v.sku);
      if (s && !porSku.has(s)) porSku.set(s, p);
    }
    if (total % 250 === 0) process.stdout.write(`\r  Shopify: ${total} produtos indexados...`);
  }
  process.stdout.write(`\r  Shopify: ${total} produtos indexados.   \n`);
  return { porSku, porHandle, total };
}

function casar(produtoBagy, indice) {
  if (CHAVE === 'sku') {
    for (const s of produtoBagy.skus) {
      const achado = indice.porSku.get(normalizar(s));
      if (achado) return achado;
    }
  }
  const h = normalizar(produtoBagy.handle);
  if (h && indice.porHandle.has(h)) return indice.porHandle.get(h);
  for (const s of produtoBagy.skus) {
    const achado = indice.porSku.get(normalizar(s));
    if (achado) return achado;
  }
  return null;
}

/**
 * Envia uma imagem. Tenta pela URL; se o Shopify recusar por tamanho,
 * baixa, reduz e reenvia em base64.
 */
async function enviarImagem(shopifyId, urlOriginal, posicao, alt) {
  const url = L.comResizeCDN(urlOriginal, cfg);

  if (DRY) return { ok: true, via: 'dry-run' };

  let r = await L.chamarShopify(cfg, limitador, 'POST', `products/${shopifyId}/images.json`, {
    image: { src: url, position: posicao, alt },
  });
  if (r.ok) return { ok: true, via: 'url', imagemId: r.corpo && r.corpo.image && r.corpo.image.id };

  const motivo = L.mensagemErro(r);
  const porTamanho = L.erroDeTamanho(r);

  // Fallback: baixar + redimensionar + enviar em base64.
  let buffer;
  try {
    buffer = await L.baixar(urlOriginal);
  } catch (e) {
    return { ok: false, via: 'url', erro: `${motivo} | download falhou: ${e.message}` };
  }

  let reduzida;
  try {
    reduzida = await L.redimensionar(buffer, cfg);
  } catch (e) {
    return { ok: false, via: 'resize', erro: `${motivo} | resize falhou: ${e.message}` };
  }

  r = await L.chamarShopify(cfg, limitador, 'POST', `products/${shopifyId}/images.json`, {
    image: {
      attachment: reduzida.buffer.toString('base64'),
      filename: L.nomeArquivo(urlOriginal, reduzida.ext),
      position: posicao,
      alt,
    },
  });
  if (r.ok) {
    return {
      ok: true,
      via: porTamanho ? 'resize(20MP)' : 'resize(fallback)',
      imagemId: r.corpo && r.corpo.image && r.corpo.image.id,
      de: `${reduzida.origem.largura}x${reduzida.origem.altura} (${reduzida.origem.mp}MP)`,
      para: `${reduzida.largura}x${reduzida.altura}`,
    };
  }
  return { ok: false, via: 'resize', erro: `${motivo} | apos resize: ${L.mensagemErro(r)}` };
}

// ------------------------------------------------------------- execucao ---

async function principal() {
  if (!cfg.loja || !cfg.token) {
    console.error('Faltam SHOPIFY_STORE e/ou SHOPIFY_TOKEN. Copie .env.exemplo para .env e preencha.');
    process.exit(1);
  }

  console.log('== Migracao de imagens Bagy -> Shopify ==');
  console.log(`   loja=${cfg.loja}  api=${cfg.apiVersion}  maxDim=${cfg.maxDim}px  chave=${CHAVE}${DRY ? '  [DRY-RUN]' : ''}`);
  if (cfg.cdnResizeParams) console.log(`   resize no CDN: ?${cfg.cdnResizeParams}`);

  const fonte = args.fonte === 'csv' ? 'csv' : 'bagy';
  const produtos = fonte === 'csv'
    ? lerProdutosCSV(args.arquivo || 'imagens.csv')
    : await lerProdutosBagy();
  console.log(`   ${produtos.length} produtos na origem (${fonte}).`);

  const indice = await indexarShopify();
  const feitos = L.carregarEstado(cfg.estado);
  if (feitos.size) console.log(`   ${feitos.size} imagens ja processadas em ${cfg.estado} (serao puladas).`);

  const resumo = { enviadas: 0, redimensionadas: 0, puladas: 0, semMatch: 0, falhas: 0, produtos: 0 };
  const falhas = [];

  for (const p of produtos) {
    if (resumo.produtos >= LIMITE) break;
    const alvo = casar(p, indice);
    if (!alvo) {
      resumo.semMatch++;
      falhas.push({ produto: p.nome || p.id, erro: 'sem produto correspondente no Shopify', skus: p.skus });
      continue;
    }
    if (!FORCAR && (alvo.images || []).length > 0) { resumo.puladas++; continue; }
    if (!p.imagens.length) { resumo.puladas++; continue; }

    resumo.produtos++;
    console.log(`\n[${resumo.produtos}] ${p.nome || p.id} -> Shopify ${alvo.id} (${p.imagens.length} imagem(ns))`);

    let posicao = (alvo.images || []).length;
    for (const url of p.imagens) {
      posicao++;
      const chave = `${alvo.id}::${url}`;
      if (feitos.has(chave) && feitos.get(chave).ok) { resumo.puladas++; continue; }

      const res = await enviarImagem(alvo.id, url, posicao, p.nome || '');
      L.gravarEstado(cfg.estado, { chave, produto: alvo.id, url, ...res, em: new Date().toISOString() });

      if (res.ok) {
        resumo.enviadas++;
        if (String(res.via).startsWith('resize')) {
          resumo.redimensionadas++;
          console.log(`    ok  ${res.via}  ${res.de} -> ${res.para}`);
        } else {
          console.log(`    ok  ${res.via}`);
        }
      } else {
        resumo.falhas++;
        falhas.push({ produto: alvo.id, url, erro: res.erro });
        console.log(`    FALHA  ${res.erro}`);
      }
    }
  }

  console.log('\n== Resumo ==');
  console.log(`  imagens enviadas .......... ${resumo.enviadas}`);
  console.log(`  destas, redimensionadas ... ${resumo.redimensionadas}`);
  console.log(`  puladas ................... ${resumo.puladas}`);
  console.log(`  sem match no Shopify ...... ${resumo.semMatch}`);
  console.log(`  falhas .................... ${resumo.falhas}`);

  if (falhas.length) {
    fs.writeFileSync('falhas.json', JSON.stringify(falhas, null, 2));
    console.log('  detalhes das falhas em falhas.json');
  }
  console.log(`  log completo em ${cfg.estado} (rode de novo para retomar de onde parou)`);
}

if (require.main === module) {
  principal().catch((e) => { console.error('\nErro fatal:', e.message); process.exit(1); });
}

module.exports = { enviarImagem, urlsDeImagem, lerProdutosCSV, separarCSV, casar };
