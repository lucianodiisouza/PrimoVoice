# Painel PrimoVoice para o DaVinci Resolve

Painel em Python puro (Fusion UIManager) que roda dentro do Resolve e chama o
[engine](../engine) por subprocess. Design de 2 processos: o painel usa o Python
embutido do Resolve; o engine roda no seu venv isolado com PyTorch/MPS.

## Instalação

1. Instale o engine primeiro:
   ```bash
   cd ../engine && ./setup.sh
   ```
2. Faça o `PrimoVoice.py` aparecer no menu de Scripts do Resolve. Ou copie, ou
   (melhor, mantém sincronizado com o git) crie um symlink na pasta de scripts do usuário:
   ```bash
   ln -s "$PWD/PrimoVoice.py" \
     "$HOME/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/PrimoVoice.py"
   ```
3. No Resolve: **Workspace ▸ Scripts ▸ PrimoVoice**.

> O symlink aponta pro repo, então o script achará o engine em `../engine` a partir
> do caminho real do arquivo.

## Uso

1. Abra o projeto e selecione a timeline com a narração.
2. Escolha um **preset** (Podcast, Narração, Entrevista ou Máxima qualidade) — os
   sliders, qualidade da voz e toggle do Demucs são aplicados de uma vez. Ou
   deixe em **Personalizado** e ajuste os sliders à mão.
3. (Opcional) Desmarque **Manter original na timeline (A/B)** se não quiser a
   faixa extra de comparação. Com ela marcada, a timeline ganha duas faixas
   lado a lado: `PrimoVoice · enhanced` e `PrimoVoice · original`. Mute/solo
   pra comparar.
4. **Processar timeline** → renderiza o áudio, limpa, e adiciona a(s) nova(s)
   faixa(s).

### Presets disponíveis

| Preset | Speech | Music | Background | Backend |
|---|---|---|---|---|
| Podcast | 100 | 10 | 10 | DeepFilterNet |
| Narração | 100 | 0 | 5 | DeepFilterNet |
| Entrevista | 100 | 20 | 30 | DeepFilterNet |
| Máxima qualidade | 100 | 15 | 8 | Resemble |

Definidos em [`engine/vc/presets.py`](../engine/vc/presets.py). Mexer num slider
volta o ComboBox pra "Personalizado" pra você saber que o painel não vai
sobrescrever o ajuste.

### A/B no Resolve

Com **Manter original** marcado, o resultado fica óbvio: duas faixas na timeline,
mesma posição, com nomes diferentes. Mute uma, escute a outra, inverta. Quando
decidir qual gosta, delete a faixa perdedora (botão direito na track header →
"Delete Track").

## Requisitos

- DaVinci Resolve (o render de áudio via API funciona nas versões recentes;
  algumas features de render podem exigir o **Studio**).
- Engine instalado em `../engine/.venv`.
- Resemble-Enhance (opcional, só pro preset **Máxima qualidade**):
  ```bash
  engine/.venv/bin/pip install -e .[resemble]  # ou: pip install resemble-enhance
  ```
