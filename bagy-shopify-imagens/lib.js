'use strict';
/**
 * Funcoes compartilhadas: config, .env, rate limit, Shopify, download e resize.
 *
 * Contexto do problema:
 *   O Shopify recusa imagens com mais de 20 MEGAPIXELS (largura x altura),
 *   nao 20 megabytes. Uma foto de 6000x4000 = 24 MP e barrada com HTTP 422:
 *   "The pixel limit is 20 megapixels. Resize your image and upload it again."
 *   Limites do Shopify: 20 MP e 20 MB por arquivo.
 */

const fs = require('fs');
const path = require('path');

// ---------------------------------------------------------------- .env ----

function carregarEnv(arquivo) {
  const alvo = arquivo || path.join(process.cwd(), '.env');
  if (!fs.existsSync(alvo)) return;
  for (const linha of fs.readFileSync(alvo, 'utf8').split(/\r?\n/)) {
    const m = linha.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
    if (!m) continue;
    let valor = m[2].trim();
    if (/^".*"$/.test(valor) || /^'.*'$/.test(valor)) valor = valor.slice(1, -1);
    if (process.env[m[1]] === undefined) process.env[m[1]] = valor;
  }
}

// --------------------------------------------------------------- config ---

function lerConfig() {
  carregarEnv();
  const loja = (process.env.SHOPIFY_STORE || '').trim().replace(/\/+$/, '');
  return {
    loja,
    token: (process.env.SHOPIFY_TOKEN || '').trim(),
    apiVersion: (process.env.SHOPIFY_API_VERSION || '2025-07').trim(),

    bagyApi: (process.env.BAGY_API || 'https://api.dooca.store').replace(/\/+$/, ''),
    bagyToken: (process.env.BAGY_TOKEN || '').trim(),
    cdnBase: (process.env.BAGY_CDN_BASE || '').replace(/\/+$/, ''),

    // Se o CDN da Bagy aceitar redimensionamento por querystring, informe aqui
    // (ex.: "w=2048&h=2048&fit=contain"). Descubra rodando `node diagnostico.js`.
    cdnResizeParams: (process.env.CDN_RESIZE_PARAMS || '').replace(/^[?&]/, '').trim(),

    maxDim: Number(process.env.MAX_DIM || 2048),
    qualidade: Number(process.env.JPEG_QUALITY || 85),
    porSegundo: Number(process.env.SHOPIFY_RPS || 2),
    estado: process.env.ARQUIVO_ESTADO || 'estado.jsonl',
  };
}

function baseShopify(cfg) {
  // Aceita "loja.myshopify.com" ou uma URL completa (util para testes locais).
  const raiz = /^https?:\/\//.test(cfg.loja) ? cfg.loja : `https://${cfg.loja}`;
  return `${raiz}/admin/api/${cfg.apiVersion}`;
}

// ----------------------------------------------------------- rate limit ---

class Limitador {
  constructor(porSegundo) {
    this.intervalo = 1000 / Math.max(0.2, porSegundo);
    this.proximo = 0;
  }
  async aguardar() {
    const agora = Date.now();
    const alvo = Math.max(agora, this.proximo);
    this.proximo = alvo + this.intervalo;
    if (alvo > agora) await dormir(alvo - agora);
  }
}

const dormir = (ms) => new Promise((r) => setTimeout(r, ms));

// ------------------------------------------------------------- Shopify ----

/**
 * Chamada REST com retry automatico em 429 (rate limit) e 5xx.
 * Retorna { ok, status, corpo, headers }.
 */
async function chamarShopify(cfg, limitador, metodo, caminho, corpo, tentativa = 0) {
  await limitador.aguardar();
  const url = caminho.startsWith('http') ? caminho : `${baseShopify(cfg)}/${caminho.replace(/^\//, '')}`;
  let resp;
  try {
    resp = await fetch(url, {
      method: metodo,
      headers: {
        'X-Shopify-Access-Token': cfg.token,
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: corpo ? JSON.stringify(corpo) : undefined,
    });
  } catch (e) {
    if (tentativa < 4) {
      await dormir(2000 * 2 ** tentativa);
      return chamarShopify(cfg, limitador, metodo, caminho, corpo, tentativa + 1);
    }
    return { ok: false, status: 0, corpo: { erro: String(e && e.message || e) }, headers: new Map() };
  }

  if ((resp.status === 429 || resp.status >= 500) && tentativa < 5) {
    const espera = Number(resp.headers.get('retry-after') || 0) * 1000 || 1000 * 2 ** tentativa;
    await dormir(espera);
    return chamarShopify(cfg, limitador, metodo, caminho, corpo, tentativa + 1);
  }

  const texto = await resp.text();
  let json = null;
  try { json = texto ? JSON.parse(texto) : null; } catch { json = { raw: texto }; }
  return { ok: resp.ok, status: resp.status, corpo: json, headers: resp.headers };
}

/** Percorre todas as paginas de produtos do Shopify (cursor via header Link). */
async function* listarProdutosShopify(cfg, limitador) {
  let caminho = 'products.json?limit=250&fields=id,handle,title,images,variants,status';
  while (caminho) {
    const r = await chamarShopify(cfg, limitador, 'GET', caminho);
    if (!r.ok) throw new Error(`Falha ao listar produtos Shopify (HTTP ${r.status}): ${JSON.stringify(r.corpo)}`);
    for (const p of (r.corpo && r.corpo.products) || []) yield p;
    caminho = proximaPagina(r.headers.get('link'));
  }
}

function proximaPagina(link) {
  if (!link) return null;
  for (const parte of link.split(',')) {
    const m = parte.match(/<([^>]+)>\s*;\s*rel="?next"?/i);
    if (m) return m[1];
  }
  return null;
}

// ------------------------------------------------------ imagens / resize --

/** Aplica os parametros de resize do CDN na URL original, se configurados. */
function comResizeCDN(url, cfg) {
  if (!cfg.cdnResizeParams) return url;
  return url + (url.includes('?') ? '&' : '?') + cfg.cdnResizeParams;
}

async function baixar(url, tentativa = 0) {
  try {
    const resp = await fetch(url, { headers: { 'User-Agent': 'migrador-bagy-shopify/1.0' } });
    if (!resp.ok) throw new Error(`HTTP ${resp.status} ao baixar ${url}`);
    return Buffer.from(await resp.arrayBuffer());
  } catch (e) {
    if (tentativa < 3) {
      await dormir(1500 * 2 ** tentativa);
      return baixar(url, tentativa + 1);
    }
    throw e;
  }
}

/**
 * Reduz a imagem para caber em maxDim x maxDim (mantendo proporcao).
 * - respeita a orientacao EXIF (.rotate())
 * - preserva transparencia: com alpha vira PNG, sem alpha vira JPEG
 * - nunca aumenta uma imagem menor que o limite
 */
async function redimensionar(buffer, cfg) {
  const sharp = require('sharp');
  const entrada = sharp(buffer, { limitInputPixels: 1e9, failOn: 'none' });
  const meta = await entrada.metadata();

  let pipeline = entrada.rotate().resize({
    width: cfg.maxDim,
    height: cfg.maxDim,
    fit: 'inside',
    withoutEnlargement: true,
  });

  let ext;
  if (meta.hasAlpha) {
    pipeline = pipeline.png({ compressionLevel: 9 });
    ext = 'png';
  } else {
    pipeline = pipeline.jpeg({ quality: cfg.qualidade, mozjpeg: true, progressive: true });
    ext = 'jpg';
  }

  const { data, info } = await pipeline.toBuffer({ resolveWithObject: true });
  return {
    buffer: data,
    ext,
    largura: info.width,
    altura: info.height,
    origem: { largura: meta.width, altura: meta.height, mp: mp(meta.width, meta.height) },
  };
}

const mp = (w, h) => (w && h ? +((w * h) / 1e6).toFixed(2) : null);

function nomeArquivo(url, ext) {
  let base;
  try {
    base = path.basename(new URL(url).pathname) || 'imagem';
  } catch {
    base = 'imagem';
  }
  base = base.replace(/\.[a-z0-9]+$/i, '').replace(/[^a-zA-Z0-9._-]/g, '-').slice(0, 80) || 'imagem';
  return `${base}.${ext}`;
}

/** Heuristica: o 422 do Shopify foi por limite de pixels/tamanho? */
function erroDeTamanho(resposta) {
  if (!resposta || resposta.status !== 422) return false;
  const texto = JSON.stringify(resposta.corpo || {});
  return /megapixel|pixel limit|too large|file size|resize your image/i.test(texto);
}

function mensagemErro(resposta) {
  const c = resposta && resposta.corpo;
  if (!c) return `HTTP ${resposta && resposta.status}`;
  if (c.errors) return typeof c.errors === 'string' ? c.errors : JSON.stringify(c.errors);
  return JSON.stringify(c).slice(0, 400);
}

// -------------------------------------------------------- estado (JSONL) --

function carregarEstado(arquivo) {
  const feitos = new Map();
  if (!fs.existsSync(arquivo)) return feitos;
  for (const linha of fs.readFileSync(arquivo, 'utf8').split(/\r?\n/)) {
    if (!linha.trim()) continue;
    try {
      const r = JSON.parse(linha);
      if (r.chave) feitos.set(r.chave, r);
    } catch { /* linha corrompida: ignora */ }
  }
  return feitos;
}

function gravarEstado(arquivo, registro) {
  fs.appendFileSync(arquivo, JSON.stringify(registro) + '\n');
}

module.exports = {
  carregarEnv, lerConfig, baseShopify, Limitador, dormir,
  chamarShopify, listarProdutosShopify, proximaPagina,
  comResizeCDN, baixar, redimensionar, nomeArquivo, mp,
  erroDeTamanho, mensagemErro, carregarEstado, gravarEstado,
};
