# PrimoVoice

Realce de voz para o **DaVinci Resolve** — o mesmo tipo de resultado do Adobe
Podcast (voz destacada, ruído isolado, som natural sem ficar metálico),
rodando **local** na sua máquina e **de graça**, com controle independente de
**Speech / Music / Background**.

Feito para Apple Silicon (macOS), usando modelos open-source que rodam
localmente.

## Como funciona

O PrimoVoice imita a arquitetura da versão paga do Adobe Podcast em duas
etapas:

1. **Isolamento generativo da voz** — em vez de só filtrar ruído (que deixa a
   voz metálica, como o noise suppression clássico), um modelo neural
   *reconstrói* a voz limpa.
2. **Separação de fontes** — o que não é voz é separado em **música** e
   **ruído de fundo**, pra você dosar cada faixa independentemente antes do
   remix.

```
áudio → [isolar voz] → voz limpa
             │
             └─ resíduo → [Demucs] → música + fundo
                                        │
   voz·ganho + música·ganho + fundo·ganho → [remix] → saída
```

## Modelos (baixados sob demanda, estilo AutoSubs)

| Modelo | Função | Tamanho |
|---|---|---|
| DeepFilterNet3 | limpeza da voz (default) | ~20 MB |
| Demucs (htdemucs) | separar música / fundo | ~80 MB |
| Resemble-Enhance | voz generativa (qualidade máxima, opcional) | ~300 MB |

Ficam em cache em `~/Library/Application Support/PrimoVoice/models`.

## Estrutura

```
engine/     # o "cérebro": CLI Python em venv isolado (torch/MPS)
resolve/    # painel/script que roda dentro do DaVinci Resolve (export → engine → import)
tests/      # smoke test do pipeline (sem GPU, sem Resolve)
```

## Uso (engine, standalone)

```bash
cd engine
./setup.sh                       # cria o venv e instala as deps
source .venv/bin/activate

python -m vc.cli models          # lista modelos e o que já está baixado
python -m vc.cli presets         # lista presets de mix
python -m vc.cli process entrada.wav -o saida.wav --preset podcast
# ou com ajustes finos em cima de um preset:
python -m vc.cli process entrada.wav -o saida.wav --preset podcast --music 20
```

`--preset` aceita `podcast`, `narration`, `interview` e `max-quality`. Quaisquer
flags explícitas (`--speech`, `--music`, `--bg`, `--enhance`, `--no-separate`)
sobrescrevem o preset. Detalhes em [`engine/vc/presets.py`](engine/vc/presets.py).

## Uso (painel no DaVinci Resolve)

Veja [resolve/README.md](resolve/README.md). Resumo:

1. Instale o engine (`engine/setup.sh`).
2. Symlink o `resolve/PrimoVoice.py` na pasta de Scripts do Resolve.
3. **Workspace ▸ Scripts ▸ PrimoVoice**.
4. Escolha um preset ou ajuste os sliders à mão.
5. (A/B) Deixe **Manter original na timeline** marcado pra ganhar duas faixas
   lado a lado: `PrimoVoice · enhanced` e `PrimoVoice · original`. Mute/solo
   pra comparar; delete a perdedora quando decidir.

## Testes

```bash
# Engine instalado + modelos deepfilter e demucs
tests/smoke.sh
```

Roda o pipeline de ponta a ponta num fixture de 6s e valida duração, sample
rate e nível (`max_volume` entre -50 e -0.5 dBFS). Saída em `tests/out/`
(não versionado).

## Roadmap

- [x] Engine: isolar voz + separar + remix com ganhos
- [x] Gerenciador de modelos (download sob demanda)
- [x] Painel no DaVinci Resolve (export/import via API Python)
- [x] Backend Resemble-Enhance (qualidade máxima)
- [x] Presets de mix (`podcast`, `narration`, `interview`, `max-quality`)
- [x] A/B preview via tracks paralelas na timeline
- [x] Smoke test reproduzível do pipeline

## Licença

[MIT](LICENSE) · construído sobre DeepFilterNet, Demucs e Resemble-Enhance
(todos MIT).
