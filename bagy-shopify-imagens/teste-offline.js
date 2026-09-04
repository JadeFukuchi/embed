#!/usr/bin/env node
'use strict';
/**
 * Teste offline: sobe um CDN falso (foto de 6000x4000 = 24 MP) e um Shopify falso
 * que recusa `src` com o mesmo 422 do print ("The pixel limit is 20 megapixels")
 * e so aceita a imagem em base64 dentro do limite.
 *
 *   node teste-offline.js
 *
 * Serve para provar que o fallback de redimensionamento funciona sem precisar
 * tocar na loja de verdade.
 */

const http = require('http');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');
const sharp = require('sharp');

const LIMITE_PIXELS = 20e6;

async function principal() {
  const grande = await sharp({
    create: { width: 6000, height: 4000, channels: 3, background: { r: 200, g: 120, b: 160 } },
  }).jpeg({ quality: 80 }).toBuffer();
  console.log(`CDN falso: foto de 6000x4000 (24 MP, ${(grande.length / 1024 / 1024).toFixed(2)} MB)`);

  const recebidas = [];
  const servidor = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://localhost');
    const responder = (status, corpo, headers = {}) => {
      res.writeHead(status, { 'Content-Type': 'application/json', ...headers });
      res.end(JSON.stringify(corpo));
    };

    if (url.pathname === '/cdn/foto.jpg') {
      res.writeHead(200, { 'Content-Type': 'image/jpeg' });
      return res.end(grande);
    }

    if (url.pathname.endsWith('/products.json')) {
      return responder(200, {
        products: [{ id: 1, handle: 'calcinha-base-off', title: 'Calcinha Base Off',
                     images: [], variants: [{ id: 11, sku: 'ABC123' }] }],
      });
    }

    if (/\/products\/1\/images\.json$/.test(url.pathname) && req.method === 'POST') {
      const corpo = JSON.parse(await texto(req));
      const img = corpo.image || {};
      if (img.src) {
        recebidas.push({ tipo: 'src' });
        return responder(422, { errors: { image: ['The pixel limit is 20 megapixels. Resize your image and upload it again.'] } });
      }
      const buf = Buffer.from(img.attachment, 'base64');
      const meta = await sharp(buf).metadata();
      const pixels = meta.width * meta.height;
      recebidas.push({ tipo: 'attachment', largura: meta.width, altura: meta.height, bytes: buf.length });
      if (pixels > LIMITE_PIXELS) {
        return responder(422, { errors: { image: ['The pixel limit is 20 megapixels. Resize your image and upload it again.'] } });
      }
      return responder(200, { image: { id: 999, width: meta.width, height: meta.height } });
    }

    return responder(404, { errors: 'nao encontrado' });
  });

  await new Promise((r) => servidor.listen(0, '127.0.0.1', r));
  const porta = servidor.address().port;

  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'teste-bagy-'));
  fs.writeFileSync(path.join(dir, 'imagens.csv'), `sku,image_url\nABC123,http://127.0.0.1:${porta}/cdn/foto.jpg\n`);

  // spawn assincrono: o servidor mock vive neste mesmo processo e precisa
  // continuar atendendo enquanto o migrador roda.
  let saida;
  try {
    saida = await rodar(process.execPath, [path.join(__dirname, 'migrar-imagens.js'), '--fonte=csv', '--arquivo=imagens.csv'], {
      cwd: dir,
      env: { ...process.env, SHOPIFY_STORE: `http://127.0.0.1:${porta}`, SHOPIFY_TOKEN: 'teste', MAX_DIM: '2048', SHOPIFY_RPS: '50' },
    });
  } catch (e) {
    servidor.close();
    throw e;
  }
  const porta2 = porta;

  console.log('\n--- saida do migrador ---');
  console.log(saida.trim());
  console.log('--- fim ---\n');

  const attach = recebidas.find((r) => r.tipo === 'attachment');
  const erros = [];
  if (!recebidas.some((r) => r.tipo === 'src')) erros.push('nao tentou enviar pela URL primeiro');
  if (!attach) erros.push('nao caiu no fallback de redimensionamento');
  if (attach && attach.largura * attach.altura > LIMITE_PIXELS) erros.push('imagem redimensionada ainda passa de 20 MP');
  if (attach && Math.max(attach.largura, attach.altura) !== 2048) erros.push(`esperava lado maior 2048, veio ${attach.largura}x${attach.altura}`);
  if (!/imagens enviadas \.+ 1/.test(saida)) erros.push('resumo nao contabilizou 1 imagem enviada');

  // 2a rodada: precisa retomar do estado.jsonl e nao reenviar nada.
  const antes = recebidas.length;
  const saida2 = await rodar(process.execPath, [path.join(__dirname, 'migrar-imagens.js'), '--fonte=csv', '--arquivo=imagens.csv', '--forcar'], {
    cwd: dir,
    env: { ...process.env, SHOPIFY_STORE: `http://127.0.0.1:${porta2}`, SHOPIFY_TOKEN: 'teste', MAX_DIM: '2048', SHOPIFY_RPS: '50' },
  });
  if (recebidas.length !== antes) erros.push('2a rodada reenviou imagem em vez de retomar do estado.jsonl');
  if (!/puladas \.+ 1/.test(saida2)) erros.push('2a rodada nao marcou a imagem como pulada');

  console.log(`Shopify falso recebeu: ${JSON.stringify(recebidas)}`);
  if (erros.length) {
    servidor.close();
    console.error('FALHOU:\n - ' + erros.join('\n - '));
    process.exit(1);
  }
  servidor.close();
  console.log(`OK: 24 MP recusados pela URL -> reenviados como ${attach.largura}x${attach.altura} (${(attach.bytes / 1024).toFixed(0)} KB) e aceitos.`);
}

function rodar(cmd, args, opcoes) {
  return new Promise((resolve, reject) => {
    const filho = spawn(cmd, args, { ...opcoes, stdio: ['ignore', 'pipe', 'pipe'] });
    let saida = '';
    filho.stdout.on('data', (d) => (saida += d));
    filho.stderr.on('data', (d) => (saida += d));
    filho.on('error', reject);
    filho.on('close', (codigo) => (codigo === 0 ? resolve(saida) : reject(new Error(`migrador saiu com codigo ${codigo}:\n${saida}`))));
  });
}

function texto(req) {
  return new Promise((resolve, reject) => {
    let d = '';
    req.on('data', (c) => (d += c));
    req.on('end', () => resolve(d));
    req.on('error', reject);
  });
}

principal().catch((e) => { console.error('Erro no teste:', e); process.exit(1); });
