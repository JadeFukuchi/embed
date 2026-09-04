# Correção do erro 422 na carga de imagens (Bagy → Shopify)

## Diagnóstico

O bloco "Insere imagem no produto" está retornando:

```
POST https://panoresortwear.myshopify.com/admin/api/2025-07/products/{id}/images.json
body: { "image": { "src": "https://cdn.dooca.store/9528/products/....jpg?v=..." } }

422 → { "errors": { "image": ["The pixel limit is 20 megapixels. Resize your image and upload it again."] } }
```

**O limite estourado é de resolução (20 megapixels), não de tamanho de arquivo.**
São dois limites distintos do Shopify:

| Limite | Valor |
|---|---|
| Resolução (largura × altura) | **20 MP** — ex.: 4472 × 4472 |
| Tamanho do arquivo | 20 MB |

Uma foto de 6000 × 4000 tem 24 MP e é recusada mesmo pesando 2 MB. Compressão
JPEG não resolve — é preciso reduzir as **dimensões**.

Os ~1200 produtos já estão criados no Shopify. Não é necessário reimportar
catálogo, apenas anexar as imagens.

## Correção — opção 1 (mais barata, testar primeiro)

Verificar se o CDN da Dooca aceita redimensionamento por querystring. Abrir no
navegador:

```
https://cdn.dooca.store/9528/products/calcinha-base-off-2-03.jpg?v=1698416331&w=2048
```

Se voltar a imagem reduzida, basta acrescentar os parâmetros no `src` do bloco
atual — nenhuma outra mudança no fluxo:

```
...calcinha-base-off-2-03.jpg?v=1698416331&w=2048&h=2048&fit=contain
```

Variantes para testar, caso `w` não funcione: `width=2048`, `resize=2048`,
`size=2048`, `d=2048x2048`.

## Correção — opção 2 (funciona sempre)

Mesmo endpoint, mesmos headers. Muda apenas o campo do corpo: em vez de `src`
(URL), enviar `attachment` (a imagem já reduzida, em base64):

```json
{
  "image": {
    "attachment": "<base64 da imagem reduzida>",
    "filename": "calcinha-base-off-2-03.jpg",
    "position": 1
  }
}
```

### Se o fluxo for n8n (sem código)

Entre o bloco que obtém a URL da Bagy e o bloco que insere no produto:

1. **HTTP Request** — `GET` na URL da Bagy, *Response Format:* `File`
2. **Edit Image** — *Operation:* `Resize`, 2048 × 2048, *Option:* `Only if larger`
3. **Code** — converter o binário para base64
4. **HTTP Request** — `POST .../products/{id}/images.json` com o corpo acima

### Se preferirem script pronto

O arquivo `bloco-imagem-shopify.js` (anexo) já implementa tudo. Node 18+ e
`npm install sharp`.

**Como função, dentro do fluxo existente:**

```js
const { enviarImagem } = require('./bloco-imagem-shopify');

await enviarImagem('9597919068380',
  'https://cdn.dooca.store/9528/products/calcinha-base-off-2-03.jpg?v=1698416331');
```

**Em lote, para reprocessar a carga inteira:**

```bash
export SHOPIFY_STORE=panoresortwear.myshopify.com
export SHOPIFY_TOKEN=shpat_xxxxx        # escopo write_products
npm install sharp
node bloco-imagem-shopify.js imagens.csv
```

`imagens.csv` — uma linha por imagem, na ordem em que devem aparecer na galeria:

```csv
product_id,image_url
9597919068380,https://cdn.dooca.store/9528/products/calcinha-base-off-2-03.jpg?v=1698416331
9597919068380,https://cdn.dooca.store/9528/products/calcinha-base-off-2-04.jpg?v=1698416331
```

Também aceita JSON: `[{"product_id":"...","image_url":"..."}]`.

## O que o script faz

1. Tenta enviar por `src`, exatamente como o bloco atual — banda zero, o Shopify
   baixa sozinho. A maioria das fotos passa nessa etapa.
2. Só quando o Shopify recusa é que baixa a foto, reduz e reenvia como
   `attachment`.

Detalhes de implementação:

- **Qualidade:** reamostragem Lanczos3, mozjpeg qualidade 90, croma 4:4:4. Sem
  perda visível. 2048 px no lado maior é o tamanho recomendado pela Shopify para
  foto de produto; `MAX_DIM=4000` também passa (16 MP) se quiserem mais folga.
- Respeita orientação EXIF (`.rotate()`), preserva alpha (PNG continua PNG) e
  nunca amplia imagem menor que o limite.
- Rate limit de 2 req/s (`SHOPIFY_RPS=4` no Plus) com retry em 429 e 5xx.
- **Idempotente:** grava `imagens-enviadas.jsonl`. Rodar de novo retoma de onde
  parou, sem duplicar imagem no produto.
- Erros consolidados em `falhas.json` para reprocessamento.

Tempo estimado: ~1200 produtos × 4 imagens ≈ 4800 chamadas ≈ 40 min a 2 req/s.

## Verificação sem tocar na loja

```bash
node teste-bloco.js
```

Sobe um CDN falso com uma foto de 6000 × 4000 e um Shopify falso que devolve o
mesmo 422. Confirma que o fallback reduz para 2048 × 1365 e é aceito, e que a
reexecução não duplica.

## Observação

O endpoint `products/{id}/images.json` é REST, considerada legada pelo Shopify
(o equivalente atual é a mutation GraphQL `productCreateMedia` com staged
uploads). Para uma carga única a REST resolve; se a sincronização virar rotina
contínua, vale planejar a migração para GraphQL.
