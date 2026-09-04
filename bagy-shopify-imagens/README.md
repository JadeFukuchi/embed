# Migração de imagens Bagy/Dooca → Shopify

Resolve o erro `422 — "The pixel limit is 20 megapixels. Resize your image and upload it again."`
que aparece na carga de produtos.

## O que realmente está acontecendo

O limite estourado **não é de 20 MB, é de 20 megapixels** (largura × altura).
São dois limites diferentes do Shopify:

| Limite do Shopify | Valor | O seu caso |
|---|---|---|
| Resolução | **20 MP** (ex.: 4472 × 4472) | é este que está estourando |
| Tamanho do arquivo | 20 MB | provavelmente ok |

Uma foto de 6000 × 4000 tem 24 MP e é recusada mesmo pesando 3 MB. Por isso o
bloco `POST /products/{id}/images.json` com `image.src` volta 422 — o Shopify
baixa a imagem da Bagy, mede, e rejeita.

**Não é preciso refazer os 1200 produtos.** Eles já estão no Shopify; falta só
anexar as imagens. É exatamente o que este script faz.

## Como funciona

Para cada imagem, em ordem:

1. **Tenta pela URL** (`image.src`), igual à integração atual — banda zero, o
   Shopify baixa sozinho. A grande maioria das fotos passa aqui.
2. **Se voltar 422**, baixa a foto, reduz para caber em `MAX_DIM × MAX_DIM`
   (padrão 2048, proporção preservada) e reenvia como `image.attachment`
   (base64). Aí passa.

Detalhes que evitam dor de cabeça:

- Respeita a orientação EXIF (foto não sai deitada).
- Preserva transparência: PNG com alpha continua PNG; o resto vira JPEG.
- Nunca aumenta imagem pequena.
- Respeita o rate limit do Shopify (2 req/s) e faz retry em 429/5xx.
- **Retomável**: grava `estado.jsonl` a cada imagem. Se cair na metade, rode de
  novo que ele continua de onde parou, sem duplicar.
- `--dry-run` para simular antes de tocar na loja.

## Instalação

```bash
cd bagy-shopify-imagens
npm install
cp .env.exemplo .env   # preencha SHOPIFY_STORE e SHOPIFY_TOKEN
```

O token sai de **Settings → Apps and sales channels → Develop apps → Create an
app**, com os escopos `read_products` e `write_products`.

## Passo 1 — diagnóstico (30 segundos)

```bash
node diagnostico.js "https://cdn.dooca.store/9528/products/calcinha-base-off-2-03.jpg?v=1698416331"
```

Ele mostra as dimensões reais da foto, confirma se ela passa dos 20 MP e testa
se o CDN da Bagy aceita redimensionar por URL (`?w=2048`, `?width=2048`, etc.).

**Se algum parâmetro funcionar**, coloque no `.env`:

```
CDN_RESIZE_PARAMS=w=2048&h=2048&fit=contain
```

Aí o Shopify já baixa a imagem pronta e nada precisa passar pela sua máquina —
é o caminho mais rápido. Se não funcionar, tudo bem: o script reduz localmente.

## Passo 2 — teste em 5 produtos

```bash
node migrar-imagens.js --fonte=bagy --limite=5
```

Confira no admin do Shopify. Se estiver bom, roda tudo:

```bash
node migrar-imagens.js --fonte=bagy
```

1200 produtos × ~4 fotos ≈ 4800 chamadas ≈ **40 minutos** no limite de 2 req/s.

### Sem API da Bagy? Use CSV

Se a empresa da integração te mandar uma planilha (ou você exportar da Bagy),
basta um CSV com uma linha por imagem:

```csv
sku,image_url
CAL-BASE-OFF-P,https://cdn.dooca.store/9528/products/calcinha-base-off-2-03.jpg?v=1698416331
CAL-BASE-OFF-P,https://cdn.dooca.store/9528/products/calcinha-base-off-2-04.jpg?v=1698416331
```

```bash
node migrar-imagens.js --fonte=csv --arquivo=imagens.csv
```

Aceita `handle` no lugar de `sku`, e separador `,` ou `;`.

## Flags

| Flag | O que faz |
|---|---|
| `--fonte=bagy\|csv` | origem da lista de imagens (padrão `bagy`) |
| `--arquivo=<path>` | CSV de entrada |
| `--dry-run` | simula, não escreve no Shopify |
| `--limite=N` | processa só N produtos |
| `--forcar` | envia mesmo em produto que já tem imagem |
| `--chave=sku\|handle` | campo usado para casar Bagy × Shopify (padrão `sku`) |

## Saídas

- `estado.jsonl` — log de cada imagem (permite retomar). **Não apague** no meio.
- `falhas.json` — só o que deu errado, para reprocessar.

## Teste offline

```bash
node teste-offline.js
```

Sobe um CDN falso com uma foto de 6000 × 4000 e um Shopify falso que devolve
exatamente o 422 do print. Prova que o fallback funciona sem tocar na loja real.

## Se a empresa da integração for corrigir o fluxo dela

Duas opções, em ordem de esforço:

1. **Uma linha:** se o diagnóstico mostrar que o CDN aceita resize, basta trocar
   o `src` no bloco de imagem de
   `https://cdn.dooca.store/.../foto.jpg?v=123`
   para
   `https://cdn.dooca.store/.../foto.jpg?v=123&w=2048&h=2048&fit=contain`.

2. **No n8n / ferramenta visual:** entre o "buscar imagem" e o "inserir imagem no
   produto", encaixar:
   `HTTP Request` (baixa a imagem como binário) → `Edit Image` (operation
   *Resize*, 2048 × 2048, *Only if larger*) → `Code`/`Move Binary Data` (para
   base64) → `HTTP Request` POST para
   `/admin/api/2025-07/products/{id}/images.json` com o corpo
   `{"image":{"attachment":"<base64>","filename":"foto.jpg"}}`.

## Observação sobre a API

O script usa a REST Admin API (`products/{id}/images.json`), a mesma da
integração atual. No Shopify ela é considerada legada — o equivalente moderno é
a GraphQL `productCreateMedia` com staged uploads. Para uma carga única a REST
resolve; se a integração for virar rotina contínua, vale migrar para GraphQL.
