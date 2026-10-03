# Suporte Distros Linux BR — Robô de Notícias 1.0

Robô GitHub Actions para coletar notícias de fontes de tecnologia/Linux, traduzir e gerar matérias originais em português do Brasil com IA e publicar no Blogger.

## Fontes ativas (3)

| Fonte | URL base | Feed principal |
|---|---|---|
| Linux.com | https://www.linux.com/ | `feed/` |
| Phoronix | https://www.phoronix.com/ | `rss.php` |
| LinuxToday | https://www.linuxtoday.com/ | `feed/` |

## IA (provedores em ordem de fallback)
1. **Gemini** — modelo principal `gemini-3.5-flash-lite`
2. **Gemini-2** — modelo fallback `gemini-3.6-flash`
3. **Groq** — modelo `openai/gpt-oss-20b`
4. **Mistral** — modelo `mistral-small-latest`

- Até **6 chamadas de texto por execução** (`MAX_GEMINI_TEXT_CALLS_PER_RUN=6`).
- Ao detectar quota/limite em um provedor, o robô passa automaticamente para o próximo.
- Se todos os provedores atingirem quota, a execução para e o restante fica para a próxima.

## Publicação
- Até **1 matéria por execução** (`MAX_POSTS_PER_RUN=1`).
- Deduplicação por URL da fonte e por URL do blog.
- A imagem do post é a **imagem original** extraída da notícia da fonte.
- Vídeos incorporados (YouTube, Vimeo, etc.) são extraídos automaticamente da fonte.
- A fonte fica registrada em comentário HTML invisível (`SUPORTE_DISTROS_LINUX_BR_SOURCE_URL`).
- O robô traduz automaticamente o conteúdo para **português do Brasil** antes de publicar.

## Filtro de Tecnologia
O robô usa uma lista de termos como `linux`, `ubuntu`, `fedora`, `debian`, `open source`, `kernel`, `segurança`, `programação`, etc., para garantir que apenas notícias de tecnologia sejam publicadas. Se houver dúvida, a regra é publicar.

## Originalidade
A verificação bloqueia apenas sinais fortes de reprodução literal:
- sequência de **15 palavras ou mais** idênticas à fonte;
- sobreposição de **8-grams acima de 12%**.

## Secrets necessários
- `BLOGGER_BLOG_ID`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `BLOGGER_REFRESH_TOKEN`
- `GEMINI_API_KEY`

### Secrets opcionais
- `GEMINI_API_KEY_2` (segunda chave Gemini)
- `GROQ_API_KEY`
- `MISTRAL_API_KEY`

## Variáveis de ambiente opcionais
- `VERBOSE_LOG=true` — ativa log detalhado
- `MAX_POSTS_PER_RUN` — padrão `1`
- `MAX_GEMINI_TEXT_CALLS_PER_RUN` — padrão `6`
- `GEMINI_MODEL` / `GEMINI_FALLBACK_MODEL`
- `GROQ_MODEL` / `MISTRAL_MODEL`
