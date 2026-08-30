# Painel PrimoVoice para o DaVinci Resolve

Painel em **Lua** (Fusion UIManager) que roda dentro do Resolve e chama o
[engine](../engine) por subprocess. Design de 2 processos: o painel usa o
**LuaJIT embutido do Resolve**; o engine roda no seu venv Python isolado com
PyTorch/MPS.

> **Resolve 21 Free**: o UIManager do Fusion é gated pra **Studio** — no Free,
> a primeira chamada que abre uma janela mostra o dialog
> "You have reached a limitation with DaVinci Resolve" e trava. Usuário Free
> deve usar a **GUI standalone** (`engine/.venv/bin/primovoice gui`) ou a CLI
> direta. O painel continua shipando porque funciona no Studio; ele só não
> consegue abrir janela no Free.

> **Por que Lua e não Python?** Resolve 21 no macOS só embarca LuaJIT
> (não tem Python embed) e o menu `Workspace ▸ Scripts` na pasta `Utility/`
> **só lista arquivos `.lua`**. O AutoSubs (que aparece no seu menu) é
> exatamente isso — um script Lua no system folder.

## Instalação

O `install.sh` da raiz já cuida de tudo:

```bash
cd /caminho/do/PrimoVoice
./install.sh
```

Ele coloca o `PrimoVoice.lua` em `/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/`
(system folder, junto com o AutoSubs). Esse é o único local que o Resolve 21
no macOS lê para o menu `Utility`.

Se você moveu o install e quer re-linkar manualmente:

```bash
cp resolve/PrimoVoice.lua \
  "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/"
```

> **Por que system folder, não user folder?** O scan do Resolve 21 na
> macOS pega só `/Library/Application Support/...` (system), não
> `~/Library/Application Support/...` (user). Confirmado por teste: nem
> `.py` nem `.lua` colocados no user folder aparecem no menu, só os do
> system folder.

> O panel lê o engine de um caminho relativo (`../engine/.venv/bin/python`)
> a partir de `resolve/PrimoVoice.lua` resolvido via `debug.getinfo`. Então
> a cópia precisa ser do arquivo real (não symlink) no caminho system.

## Uso

1. Abra o projeto e selecione a timeline com a narração.
2. Escolha um **preset** (Podcast, Narração, Entrevista ou Máxima qualidade) — os
   sliders, qualidade da voz e toggle do Demucs são aplicados de uma vez. Ou
   deixe em **Personalizado** e ajuste os sliders à mão.
3. (Opcional) Desmarque **Manter original na timeline (A/B)** se não quiser a
   faixa extra de comparação. Com ela marcada, a timeline ganha duas faixas
   lado a lado: `PrimoVoice · enhanced` e `PrimoVoice · original`. Mute/solo
   pra comparar; delete a perdedora quando decidir.
4. **Processar timeline**.

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
