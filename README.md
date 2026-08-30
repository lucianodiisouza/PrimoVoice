# PrimoVoice

Realce de voz para o **DaVinci Resolve** — o mesmo tipo de resultado do Adobe Podcast
(voz destacada, ruído isolado, som natural sem ficar metálico), rodando **local** na sua
máquina e **de graça**, com controle independente de **Speech / Music / Background**.

Feito para Apple Silicon (macOS), usando modelos open-source que rodam localmente.

> Status: **em desenvolvimento** (MVP). Veja o [roadmap](#roadmap).

## Como funciona

O PrimoVoice imita a arquitetura da versão paga do Adobe Podcast em duas etapas:

1. **Isolamento generativo da voz** — em vez de só filtrar ruído (que deixa a voz
   metálica, como o noise suppression clássico), um modelo neural *reconstrói* a voz limpa.
2. **Separação de fontes** — o que não é voz é separado em **música** e **ruído de fundo**,
   para você dosar cada faixa independentemente antes do remix.

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
```

## Uso (engine, standalone)

```bash
cd engine
./setup.sh                       # cria o venv e instala as deps
source .venv/bin/activate

python -m vc.cli models          # lista modelos e o que já está baixado
python -m vc.cli process entrada.wav -o saida.wav \
    --speech 100 --music 10 --bg 10
```

## Roadmap

- [x] Engine: isolar voz + separar + remix com ganhos
- [x] Gerenciador de modelos (download sob demanda)
- [ ] Painel no DaVinci Resolve (export/import via API Python)
- [ ] Backend Resemble-Enhance (qualidade máxima)
- [ ] Presets e prévia A/B (Original vs Enhanced)

## Licença

[MIT](LICENSE) · construído sobre DeepFilterNet, Demucs e Resemble-Enhance (todos MIT).
