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
2. Ajuste **Speech / Music / Background** e escolha a qualidade da voz.
3. **Processar timeline** → renderiza o áudio, limpa, e adiciona uma nova faixa.

## Requisitos

- DaVinci Resolve (o render de áudio via API funciona nas versões recentes;
  algumas features de render podem exigir o **Studio**).
- Engine instalado em `../engine/.venv`.
