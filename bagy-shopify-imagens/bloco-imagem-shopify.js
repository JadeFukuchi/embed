#!/usr/bin/env node
'use strict';
/* ============================================================================
 * SUBSTITUTO DO BLOCO "INSERE IMAGEM NO PRODUTO"
 * Bagy/Dooca -> Shopify, com redimensionamento automatico
 * ----------------------------------------------------------------------------
 * PARA QUE SERVE
 *   O bloco atual faz:
 *     POST https://SUA-LOJA.myshopify.com/admin/api/2025-07/products/{ID}/images.json
 *     body: { "image": { "src": "https://cdn.dooca.store/9528/products/....jpg" } }
 *
 *   e volta:
 *     422 -> "The pixel limit is 20 megapixels. Resize your image and upload it again."
 *
 *   O limite do Shopify NAO e de 20 MB, e de 20 MEGAPIXELS (largura x altura).
 *   Uma foto 6000x4000 = 24 MP e recusada mesmo pesando 2 MB.
 *   Limites oficiais: 20 MP de resolucao E 20 MB de arquivo.
 *
 * O QUE ESTE ARQUIVO FAZ
 *   Mesmo endpoint, mesmos headers, mesmo body. Muda so uma coisa:
 *     1. tenta enviar por "src" (identico ao bloco de hoje, banda zero)
 *     2. se o Shopify recusar por tamanho, baixa a foto, reduz e reenvia
 *        no campo "attachment" (base64) -- que e o outro campo aceito
 *        pelo mesmo endpoint.
 *
 * QUALIDADE
 *   Reducao com Lanczos3 + mozjpeg qualidade 90 + croma 4:4:4.
 *   2048px no lado maior e o tamanho recomendado pela propria Shopify para
 *   foto de produto (o zoom da vitrine usa no maximo isso). Sem perda visivel.
 *   Quem quiser mais folga: MAX_DIM=4000 ainda passa (16 MP < 20 MP).
 *
 * COMO USAR (3 formas)
 *
 *   A) Como funcao dentro do fluxo que ja existe
 *        const { enviarImagem } = require('./bloco-imagem-shopify');
 *        await enviarImagem('9597919068380',
 *          'https://cdn.dooca.store/9528/products/calcinha-base-off-2-03.jpg?v=1698416331');
 *
 *   B) Em lote, por linha de comando (reprocessa a carga inteira)
 *        export SHOPIFY_STORE=panoresortwear.myshopify.com
 *        export SHOPIFY_TOKEN=shpat_xxxxx
 *        node bloco-imagem-shopify.js imagens.csv
 *
 *      imagens.csv (uma linha por imagem, na ordem em que devem aparecer):
 *        product_id,image_url
 *        9597919068380,https://cdn.dooca.store/9528/products/calcinha-base-off-2-03.jpg?v=1698416331
 *        9597919068380,https://cdn.dooca.store/9528/products/calcinha-base-off-2-04.jpg?v=1698416331
 *
 *      Tambem aceita JSON: [{"product_id":"...","image_url":"..."}]
 *
 *   C) Em n8n, sem codigo, no lugar do bloco atual:
 *        HTTP Request (GET a URL da Bagy, Response Format = File)
 *          -> Edit Image (Operation: Resize, 2048x2048, Option: "Only if larger")
 *          -> Code (converter binario em base64)
 *          -> HTTP Request (POST .../images.json com {"image":{"attachment": base64,
 *             "filename": "foto.jpg"}})
 *
 * REQUISITOS
 *   Node 18+ e a biblioteca sharp:   npm install sharp
 *   Token do app privado com escopo write_products.
 * ========================================================================== */

const fs = require('fs');
const path = require('path');

const CONFIG = {
  loja: process.env.SHOPIFY_STORE || 'panoresortwear.myshopify.com',
  token: process.env.SHOPIFY_TOKEN || '',
  apiVersion: process.env.SHOPIFY_API_VERSION || '2025-07',

  maxDim: Number(process.env.MAX_DIM || 2048),      // lado maior apos reducao
  qualidade: Number(process.env.JPEG_QUALITY || 90), // 90 = sem perda visivel
  porSegundo: Number(process.env.SHOPIFY_RPS || 2),  // plano padrao 2/s, Plus 4/s

  // Opcional: se o CDN da Bagy aceitar redimensionar por querystring
  // (ex.: "w=2048&h=2048&fit=contain"), o Shopify ja baixa a foto pequena e
  // nada precisa passar pelo servidor de voces. Teste abrindo no navegador:
  //   <url da foto>&w=2048   -> se voltar menor, preencha aqui.
  cdnResizeParams: (process.env.CDN_RESIZE_PARAMS || '').replace(/^[?&]/, ''),

  // Log append-only: permite reprocessar sem duplicar imagem.
  arquivoEstado: process.env.ARQUIVO_ESTADO || 'imagens-enviadas.jsonl',
};

const dormir = (ms) => new Promise((r) => setTimeout(r, ms));

// --- controle do rate limit do Shopify (2 chamadas/segundo no plano padrao) --
let proximaChamada = 0;
async function respeitarLimite() {
  const intervalo = 1000 / Math.max(0.2, CONFIG.porSegundo);
  const agora = Date.now();
  const alvo = Math.max(agora, proximaChamada);
  proximaChamada = alvo + intervalo;
  if (alvo > agora) await dormir(alvo - agora);
}

function urlEndpoint(produtoId) {
  const raiz = /^https?:\/\//.test(CONFIG.loja) ? CONFIG.loja : `https://${CONFIG.loja}`;
  return `${raiz}/admin/api/${CONFIG.apiVersion}/products/${produtoId}/images.json`;
}

/** POST no mesmo endpoint/headers do bloco atual, com retry em 429 e 5xx. */
async function postarImagem(produtoId, image, tentativa = 0) {
  await respeitarLimite();
  let resp;
  try {
    resp = await fetch(urlEndpoint(produtoId), {
      method: 'POST',
      headers: {
        'X-Shopify-Access-Token': CONFIG.token,
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify({ image }),
    });
  } catch (e) {
    if (tentativa < 4) { await dormir(2000 * 2 ** tentativa); return postarImagem(produtoId, image, tentativa + 1); }
    return { ok: false, status: 0, corpo: { errors: String((e && e.message) || e) } };
  }

  if ((resp.status === 429 || resp.status >= 500) && tentativa < 5) {
    const espera = Number(resp.headers.get('retry-after') || 0) * 1000 || 1000 * 2 ** tentativa;
    await dormir(espera);
    return postarImagem(produtoId, image, tentativa + 1);
  }

  const texto = await resp.text();
  let corpo = null;
  try { corpo = texto ? JSON.parse(texto) : null; } catch { corpo = { errors: texto }; }
  return { ok: resp.ok, status: resp.status, corpo };
}

/** O 422 foi por limite de pixels / tamanho de arquivo? */
function recusadaPorTamanho(r) {
  if (!r || r.status !== 422) return false;
  return /megapixel|pixel limit|too large|file size|resize your image/i.test(JSON.stringify(r.corpo || {}));
}

async function baixar(url, tentativa = 0) {
  try {
    const resp = await fetch(url, { headers: { 'User-Agent': 'migrador-bagy-shopify/1.0' } });
    if (!resp.ok) throw new Error(`HTTP ${resp.status} ao baixar a imagem`);
    return Buffer.from(await resp.arrayBuffer());
  } catch (e) {
    if (tentativa < 3) { await dormir(1500 * 2 ** tentativa); return baixar(url, tentativa + 1); }
    throw e;
  }
}

/**
 * Reduz mantendo proporcao e qualidade:
 *  - Lanczos3 (padrao do sharp) = melhor reamostragem para reducao
 *  - mozjpeg q90 + croma 4:4:4  = sem artefato visivel em borda e tecido
 *  - .rotate() aplica a orientacao EXIF (foto nao sai deitada)
 *  - PNG com transparencia continua PNG (JPEG faria fundo preto)
 *  - withoutEnlargement: foto pequena passa intacta
 */
async function reduzir(buffer) {
  const sharp = require('sharp');
  const entrada = sharp(buffer, { limitInputPixels: 1e9, failOn: 'none' });
  const meta = await entrada.metadata();

  let fluxo = entrada.rotate().resize({
    width: CONFIG.maxDim,
    height: CONFIG.maxDim,
    fit: 'inside',
    withoutEnlargement: true,
    kernel: 'lanczos3',
  });

  const temAlpha = !!meta.hasAlpha;
  fluxo = temAlpha
    ? fluxo.png({ compressionLevel: 9, adaptiveFiltering: true })
    : fluxo.jpeg({ quality: CONFIG.qualidade, mozjpeg: true, progressive: true, chromaSubsampling: '4:4:4' });

  const { data, info } = await fluxo.toBuffer({ resolveWithObject: true });
  return {
    buffer: data,
    ext: temAlpha ? 'png' : 'jpg',
    largura: info.width,
    altura: info.height,
    origemLargura: meta.width,
    origemAltura: meta.height,
    origemMP: +((meta.width * meta.height) / 1e6).toFixed(2),
  };
}

function nomeArquivo(url, ext) {
  let base = 'imagem';
  try { base = path.basename(new URL(url).pathname) || 'imagem'; } catch { /* url estranha */ }
  base = base.replace(/\.[a-z0-9]+$/i, '').replace(/[^a-zA-Z0-9._-]/g, '-').slice(0, 80) || 'imagem';
  return `${base}.${ext}`;
}

/* ============================================================================
 * FUNCAO PRINCIPAL — e esta que substitui o bloco do fluxo
 * ==========================================================================*/
async function enviarImagem(produtoId, urlImagem, opcoes = {}) {
  const { posicao, alt } = opcoes;

  // 1) Igual ao bloco de hoje: manda a URL e o Shopify baixa sozinho.
  const src = CONFIG.cdnResizeParams
    ? urlImagem + (urlImagem.includes('?') ? '&' : '?') + CONFIG.cdnResizeParams
    : urlImagem;

  let r = await postarImagem(produtoId, { src, position: posicao, alt });
  if (r.ok) {
    return { ok: true, via: 'src', imagemId: r.corpo && r.corpo.image && r.corpo.image.id };
  }

  const motivo = JSON.stringify((r.corpo && r.corpo.errors) || r.corpo || {}).slice(0, 300);
  const porTamanho = recusadaPorTamanho(r);

  // 2) Recusou: baixa, reduz e reenvia no campo "attachment" do MESMO endpoint.
  let bruto;
  try {
    bruto = await baixar(urlImagem);
  } catch (e) {
    return { ok: false, etapa: 'download', erro: `${motivo} | ${e.message}` };
  }

  let reduzida;
  try {
    reduzida = await reduzir(bruto);
  } catch (e) {
    return { ok: false, etapa: 'resize', erro: `${motivo} | ${e.message}` };
  }

  r = await postarImagem(produtoId, {
    attachment: reduzida.buffer.toString('base64'),
    filename: nomeArquivo(urlImagem, reduzida.ext),
    position: posicao,
    alt,
  });

  if (r.ok) {
    return {
      ok: true,
      via: porTamanho ? 'reduzida (estourava 20MP)' : 'reduzida (fallback)',
      imagemId: r.corpo && r.corpo.image && r.corpo.image.id,
      de: `${reduzida.origemLargura}x${reduzida.origemAltura} (${reduzida.origemMP} MP)`,
      para: `${reduzida.largura}x${reduzida.altura}`,
      kb: Math.round(reduzida.buffer.length / 1024),
    };
  }

  return {
    ok: false,
    etapa: 'upload',
    erro: `${motivo} | depois de reduzir: ${JSON.stringify((r.corpo && r.corpo.errors) || r.corpo || {}).slice(0, 300)}`,
  };
}

/* ============================================================================
 * MODO LOTE (linha de comando)
 * ==========================================================================*/
function lerLista(arquivo) {
  const conteudo = fs.readFileSync(arquivo, 'utf8').trim();

  if (conteudo.startsWith('[')) {
    return JSON.parse(conteudo).map((i) => ({
      produtoId: String(i.product_id || i.produto_id || i.id),
      url: i.image_url || i.url || i.src,
    }));
  }

  const linhas = conteudo.split(/\r?\n/).filter((l) => l.trim());
  const separar = (l) => l.split(/[;,](?=(?:[^"]*"[^"]*")*[^"]*$)/).map((c) => c.trim().replace(/^"|"$/g, ''));
  const cabecalho = separar(linhas[0]).map((h) => h.toLowerCase());
  const iId = cabecalho.findIndex((h) => /product_id|produto|id/.test(h));
  const iUrl = cabecalho.findIndex((h) => /image_url|url|src|imagem|foto/.test(h));
  if (iId < 0 || iUrl < 0) {
    throw new Error('O CSV precisa das colunas product_id e image_url.');
  }
  return linhas.slice(1).map(separar)
    .filter((c) => c[iId] && c[iUrl])
    .map((c) => ({ produtoId: c[iId], url: c[iUrl] }));
}

function jaEnviadas() {
  const feitas = new Set();
  if (!fs.existsSync(CONFIG.arquivoEstado)) return feitas;
  for (const linha of fs.readFileSync(CONFIG.arquivoEstado, 'utf8').split(/\r?\n/)) {
    if (!linha.trim()) continue;
    try { const r = JSON.parse(linha); if (r.ok) feitas.add(r.chave); } catch { /* linha truncada */ }
  }
  return feitas;
}

async function lote(arquivo) {
  if (!CONFIG.token) {
    console.error('Falta a variavel SHOPIFY_TOKEN (token do app privado, escopo write_products).');
    process.exit(1);
  }

  const itens = lerLista(arquivo);
  const feitas = jaEnviadas();
  const posicaoPorProduto = new Map();

  console.log(`Loja: ${CONFIG.loja} | API ${CONFIG.apiVersion} | reducao para ${CONFIG.maxDim}px`);
  console.log(`${itens.length} imagens na lista; ${feitas.size} ja enviadas anteriormente.\n`);

  const contagem = { ok: 0, reduzidas: 0, puladas: 0, erro: 0 };
  const falhas = [];

  for (let i = 0; i < itens.length; i++) {
    const { produtoId, url } = itens[i];
    const chave = `${produtoId}::${url}`;
    if (feitas.has(chave)) { contagem.puladas++; continue; }

    const posicao = (posicaoPorProduto.get(produtoId) || 0) + 1;
    posicaoPorProduto.set(produtoId, posicao);

    const res = await enviarImagem(produtoId, url, { posicao });
    fs.appendFileSync(CONFIG.arquivoEstado, JSON.stringify({ chave, produtoId, url, ...res, em: new Date().toISOString() }) + '\n');

    const prefixo = `[${i + 1}/${itens.length}] produto ${produtoId}`;
    if (res.ok) {
      contagem.ok++;
      if (res.via.startsWith('reduzida')) {
        contagem.reduzidas++;
        console.log(`${prefixo}  OK  ${res.via}: ${res.de} -> ${res.para} (${res.kb} KB)`);
      } else {
        console.log(`${prefixo}  OK  enviada pela URL`);
      }
    } else {
      contagem.erro++;
      falhas.push({ produtoId, url, etapa: res.etapa, erro: res.erro });
      console.log(`${prefixo}  ERRO (${res.etapa}): ${res.erro}`);
    }
  }

  console.log(`\nEnviadas: ${contagem.ok}  (reduzidas: ${contagem.reduzidas})`);
  console.log(`Puladas: ${contagem.puladas}   Erros: ${contagem.erro}`);
  if (falhas.length) {
    fs.writeFileSync('falhas.json', JSON.stringify(falhas, null, 2));
    console.log('Detalhes dos erros em falhas.json');
  }
  console.log(`Log em ${CONFIG.arquivoEstado} — rodar de novo continua de onde parou, sem duplicar.`);
}

if (require.main === module) {
  const arquivo = process.argv[2];
  if (!arquivo) {
    console.error('Uso: node bloco-imagem-shopify.js <imagens.csv|imagens.json>');
    process.exit(1);
  }
  lote(arquivo).catch((e) => { console.error('Erro fatal:', e.message); process.exit(1); });
}

module.exports = { enviarImagem, reduzir, CONFIG };
