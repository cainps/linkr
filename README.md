# Linkr — Encurtador de URLs + Analytics

Projeto de portfólio 
**autenticação, regras de negócio, API REST, modelagem relacional, índices/otimização de queries e um dashboard de analytics.**

Stack: Python 3.11+, Flask, SQLite (sem ORM, SQL puro), JWT, front-end em HTML/JS puro (SVG para os gráficos). Zero build.

## Rodando

```bash
pip install -r requirements.txt
python seed.py          # opcional: dados de demo  →  demo@linkr.dev / demo12345
python run.py           # http://localhost:5000
pytest                  # 24 testes
```

Variáveis de ambiente: `SECRET_KEY` (**obrigatória em produção**), `DATABASE`, `BASE_URL`, `MAX_ACTIVE_LINKS`.

## Modelagem

```
users (1) ──< links (1) ──< clicks
 id            id             id
 email UNIQUE  user_id FK     link_id FK (ON DELETE CASCADE)
 password_hash slug UNIQUE    clicked_at, country, device, browser, referrer
               target_url     visitor_hash  (sha256 — nunca guarda o IP)
               expires_at, max_clicks, click_count, is_active
```

**Índices (verificados com `EXPLAIN QUERY PLAN`)**
| Índice | Query que atende | Plano |
|---|---|---|
| `links.slug` UNIQUE | redirect (a rota mais quente) | `SEARCH ... USING INDEX (slug=?)` |
| `clicks(link_id, clicked_at)` | todas as queries de analytics | `SEARCH ... COVERING INDEX (link_id=? AND clicked_at>?)` |
| `links(user_id, created_at DESC)` | listagem paginada | `SEARCH ... USING INDEX (user_id=?)` |

`links.click_count` é um contador desnormalizado (troca um pouco de redundância por evitar `COUNT(*)` na listagem e permitir o limite de cliques atômico).

## API

| Método | Rota | |
|---|---|---|
| POST | `/api/auth/register`, `/api/auth/login` | devolve JWT (24h) |
| POST | `/api/links` | `{url, slug?, title?, expires_at?, max_clicks?}` |
| GET | `/api/links?page=&per_page=&q=` | paginação + busca |
| GET/PATCH/DELETE | `/api/links/:id` | só do dono (outro usuário recebe 404) |
| GET | `/api/links/:id/analytics?days=30` | cliques/dia, únicos, países, devices, browsers, referrers |
| GET | `/api/analytics/overview?days=30` | o mesmo, agregado + top links |
| GET | `/:slug` | **302** para o destino e registra o clique |

## Regras de negócio

- URL só `http/https`, até 2048 chars; bloqueia `localhost`, IPs privados/loopback e `.local/.internal` (evita SSRF/abuso) e links para o próprio domínio (loop).
- Slug custom: 3–32 chars `[A-Za-z0-9_-]`, palavras reservadas (`api`, `admin`…), único (409). Sem slug custom, gera base62 de 7 chars com retry em colisão. **Slug é imutável** (trocar quebraria links já divulgados).
- Expiração (precisa ser futura) → `410 Gone`. Limite de cliques → `410`, aplicado com `UPDATE ... WHERE click_count < max_clicks` (atômico, sem race condition).
- Link pausado → 404. Limite de links ativos por usuário (padrão 100) → 403.
- **Bots** (Googlebot, curl, previews de rede social…) são redirecionados, mas não contam como clique.
- Redirect é **302**, não 301: 301 é cacheado pelo navegador e os cliques seguintes nunca chegariam ao servidor.
- Auth: senha com `scrypt` + salt, comparação em tempo constante, mensagem única de erro no login (não revela se o e-mail existe), rate limit de 5 tentativas/5 min.
- Privacidade: visitantes únicos via `sha256(secret|ip|ua)`; o IP não é armazenado.

## Limitações conhecidas / próximos passos

- **País**: não há base GeoIP embutida. Vem do header `CF-IPCountry` (Cloudflare) ou `X-Country`; sem eles, fica `Unknown`. Para geolocalizar por IP, integrar MaxMind GeoLite2.
- Rate limit de login é em memória (por processo); em produção, Redis.
- SQLite escreve um clique por vez; para alto volume, trocar por Postgres e gravar cliques de forma assíncrona (fila) com agregação diária em tabela de rollup.
- Ideias: QR code, domínio customizado, UTM builder, exportar CSV, testes de carga.
