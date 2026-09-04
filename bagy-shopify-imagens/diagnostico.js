#!/usr/bin/env node
'use strict';
/**
 * Descobre, para UMA imagem da Bagy, qual estrategia de redimensionamento funciona.
 *
 *   node diagnostico.js "https://cdn.dooca.store/9528/products/calcinha-base-off-2-03.jpg?v=1698416331"
 *
 * Mostra: dimensoes reais, megapixels, se passa no limite do Shopify e quais
 * parametros de querystring o CDN da Bagy aceita para entregar a imagem menor.
 * O parametro que funcionar deve ir para CDN_RESIZE_PARAMS no .env
 * (opcional: sem ele o script simplesmente redimensiona localmente).
 */

const L = require('./lib');

const LIMITE_MP = 20;
const CANDIDATOS = [
  'w=2048',
  'w=2048&h=2048&fit=contain',
  'width=2048',
  'width=2048&height=2048',
  'resize=2048',
  'size=2048',
  'max=2048',
  'd=2048x2048',
];

async function medir(url) {
  const sharp = require('sharp');
  const inicio = Date.now();
  const buf = await L.baixar(url);
  const meta = await sharp(buf, { limitInputPixels: 1e9, failOn: 'none' }).metadata();
  return {
    bytes: buf.length,
    largura: meta.width,
    altura: meta.height,
    mp: L.mp(meta.width, meta.height),
    formato: meta.format,
    ms: Date.now() - inicio,
  };
}

const fmt = (m) =>
  `${m.largura}x${m.altura} = ${m.mp} MP | ${(m.bytes / 1024 / 1024).toFixed(2)} MB | ${m.formato} | ${m.ms}ms`;

async function principal() {
  const url = process.argv[2];
  if (!url) {
    console.error('Uso: node diagnostico.js "<url da imagem na Bagy>"');
    process.exit(1);
  }

  console.log('\n1) Imagem original');
  const original = await medir(url);
  console.log('   ' + fmt(original));
  console.log(
    original.mp > LIMITE_MP
      ? `   >>> ACIMA do limite do Shopify (${LIMITE_MP} MP). E por isso que a carga falhou com 422.`
      : `   >>> Dentro do limite de ${LIMITE_MP} MP. Se esta imagem falhou, o motivo foi outro (URL, 20MB ou formato).`
  );

  console.log('\n2) O CDN da Bagy aceita redimensionar por querystring?');
  let vencedor = null;
  for (const params of CANDIDATOS) {
    const teste = url + (url.includes('?') ? '&' : '?') + params;
    try {
      const m = await medir(teste);
      const mudou = m.largura !== original.largura || m.altura !== original.altura;
      console.log(`   ${mudou ? 'SIM ' : 'nao '} ?${params}  ->  ${m.largura}x${m.altura} (${m.mp} MP)`);
      if (mudou && m.mp <= LIMITE_MP && !vencedor) vencedor = params;
    } catch (e) {
      console.log(`   erro ?${params}  ->  ${e.message}`);
    }
  }
  console.log(
    vencedor
      ? `   >>> Use no .env:  CDN_RESIZE_PARAMS=${vencedor}\n       (assim o Shopify baixa a imagem ja reduzida, sem gastar banda sua)`
      : '   >>> O CDN nao redimensiona por URL. Sem problema: o script reduz localmente (sharp).'
  );

  console.log('\n3) Redimensionamento local (sempre funciona)');
  const cfg = L.lerConfig();
  const buf = await L.baixar(url);
  const r = await L.redimensionar(buf, cfg);
  console.log(
    `   ${r.origem.largura}x${r.origem.altura} (${r.origem.mp} MP) -> ${r.largura}x${r.altura} ` +
    `(${L.mp(r.largura, r.altura)} MP) | ${(r.buffer.length / 1024).toFixed(0)} KB | .${r.ext}`
  );
  console.log('   >>> Envio como attachment base64 no Shopify. Aprovado no limite de 20 MP.\n');
}

principal().catch((e) => { console.error('Erro:', e.message); process.exit(1); });
