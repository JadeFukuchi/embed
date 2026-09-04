#!/usr/bin/env node
'use strict';
/**
 * Teste do bloco-imagem-shopify.js sem tocar na loja real.
 *
 *   npm install sharp
 *   node teste-bloco.js
 *
 * Sobe um CDN falso servindo uma foto de 6000x4000 (24 MP) e um Shopify falso
 * que devolve exatamente o 422 "The pixel limit is 20 megapixels" quando recebe
 * `src`, e so aceita `attachment` dentro do limite.
 */

const http = require('http');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');
const sharp = require('sharp');

const LIMITE_PIXELS = 20e6;

function corpo(req) {
  return new Promise((resolve, reject) => {
    let d = '';
    req.on('data', (c) => (d += c));
    req.on('end', () => resolve(d));
    req.on('error', reject);
  });
}

function rodar(args, opcoes) {
  return new Promise((resolve, reject) => {
    const filho = spawn(process.execPath, args, { ...opcoes, stdio: ['ignore', 'pipe', 'pipe'] });
    let saida = '';
    filho.stdout.on('data', (d) => (saida += d));
    filho.stderr.on('data', (d) => (saida += d));
    filho.on('error', reject);
    filho.on('close', (c) => (c === 0 ? resolve(saida) : reject(new Error(`saiu com codigo ${c}:\n${saida}`))));
  });
}

async function principal() {
  // Foto com detalhe fino, para conferir que a reducao nao borra a imagem.
  const grande = await sharp({
    create: { width: 6000, height: 4000, channels: 3, background: { r: 235, g: 225, b: 215 } },
  })
    .composite([{
      input: Buffer.from(
        `<svg width="6000" height="4000">
           <rect width="6000" height="4000" fill="#efe7df"/>
           <circle cx="3000" cy="2000" r="1200" fill="#c86f8f"/>
           <text x="600" y="600" font-size="220" fill="#222">PANO RESORTWEAR</text>
         </svg>`
      ),
      top: 0, left: 0,
    }])
    .jpeg({ quality: 92 })
    .toBuffer();

  console.log(`CDN falso: 6000x4000 = 24 MP, ${(grande.length / 1024 / 1024).toFixed(2)} MB`);

  const recebidas = [];
  const servidor = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://localhost');
    const responder = (s, c) => { res.writeHead(s, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(c)); };

    if (url.pathname === '/cdn/foto.jpg') {
      res.writeHead(200, { 'Content-Type': 'image/jpeg' });
      return res.end(grande);
    }

    if (/\/products\/9597919068380\/images\.json$/.test(url.pathname) && req.method === 'POST') {
      const img = (JSON.parse(await corpo(req)) || {}).image || {};
      if (img.src) {
        recebidas.push({ tipo: 'src' });
        return responder(422, { errors: { image: ['The pixel limit is 20 megapixels. Resize your image and upload it again.'] } });
      }
      const buf = Buffer.from(img.attachment, 'base64');
      const meta = await sharp(buf).metadata();
      recebidas.push({ tipo: 'attachment', largura: meta.width, altura: meta.height, bytes: buf.length, filename: img.filename });
      if (meta.width * meta.height > LIMITE_PIXELS) {
        return responder(422, { errors: { image: ['The pixel limit is 20 megapixels. Resize your image and upload it again.'] } });
      }
      return responder(200, { image: { id: 4242, width: meta.width, height: meta.height } });
    }

    return responder(404, { errors: 'nao encontrado' });
  });

  await new Promise((r) => servidor.listen(0, '127.0.0.1', r));
  const porta = servidor.address().port;

  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'teste-bloco-'));
  fs.writeFileSync(
    path.join(dir, 'imagens.csv'),
    `product_id,image_url\n9597919068380,http://127.0.0.1:${porta}/cdn/foto.jpg\n`
  );

  const env = {
    ...process.env,
    SHOPIFY_STORE: `http://127.0.0.1:${porta}`,
    SHOPIFY_TOKEN: 'teste',
    MAX_DIM: '2048',
    SHOPIFY_RPS: '50',
  };

  let saida;
  try {
    saida = await rodar([path.join(__dirname, 'bloco-imagem-shopify.js'), 'imagens.csv'], { cwd: dir, env });
  } catch (e) {
    servidor.close();
    throw e;
  }

  console.log('\n--- saida ---\n' + saida.trim() + '\n--- fim ---\n');

  const erros = [];
  const attach = recebidas.find((r) => r.tipo === 'attachment');
  if (!recebidas.some((r) => r.tipo === 'src')) erros.push('nao tentou primeiro pela URL (src)');
  if (!attach) erros.push('nao caiu no reenvio com attachment');
  if (attach && attach.largura * attach.altura > LIMITE_PIXELS) erros.push('imagem reduzida ainda passa de 20 MP');
  if (attach && Math.max(attach.largura, attach.altura) !== 2048) erros.push(`esperava lado maior 2048, veio ${attach.largura}x${attach.altura}`);
  if (attach && !/\.jpg$/.test(attach.filename || '')) erros.push(`filename inesperado: ${attach.filename}`);
  if (!/Enviadas: 1/.test(saida)) erros.push('resumo nao contabilizou a imagem');

  // 2a rodada: precisa pular pelo log, sem reenviar.
  const antes = recebidas.length;
  const saida2 = await rodar([path.join(__dirname, 'bloco-imagem-shopify.js'), 'imagens.csv'], { cwd: dir, env });
  if (recebidas.length !== antes) erros.push('2a rodada reenviou a imagem em vez de pular');
  if (!/Puladas: 1/.test(saida2)) erros.push('2a rodada nao marcou como pulada');

  servidor.close();

  console.log('Shopify falso recebeu:', JSON.stringify(recebidas));
  if (erros.length) {
    console.error('FALHOU:\n - ' + erros.join('\n - '));
    process.exit(1);
  }
  console.log(
    `OK: 24 MP recusados pela URL -> reenviados como ${attach.largura}x${attach.altura} ` +
    `(${(attach.bytes / 1024).toFixed(0)} KB) e aceitos. Reexecucao nao duplicou.`
  );
}

principal().catch((e) => { console.error('Erro no teste:', e); process.exit(1); });
