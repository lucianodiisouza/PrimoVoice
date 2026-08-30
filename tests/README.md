# Testes

Smoke test do engine PrimoVoice. O objetivo é garantir que o pipeline
(isolar voz → separar → remix) roda de ponta a ponta num fixture curto, sem
precisar de GPU nem de uma timeline do Resolve.

## Conteúdo

- `sample_in.wav` — fixture de entrada: 6s, mono, 48 kHz. É a única coisa
  versionada desta pasta.
- `smoke.sh` — runner reproduzível. Roda o engine e valida a saída.
- `out/` — saída gerada pelo smoke. **Não é versionada** (está no
  `.gitignore` da raiz). Cada execução sobrescreve o `sample_out.wav`.

## Rodando

```bash
# 1) Engine tem que estar instalado
cd engine && ./setup.sh && cd ..

# 2) Modelos necessários (deepfilter é o único obrigatório pro smoke default)
engine/.venv/bin/python -m vc.cli download deepfilter
# demucs é opcional: sem ele o smoke ainda roda, mas sem faixa de música
engine/.venv/bin/python -m vc.cli download demucs

# 3) Roda
tests/smoke.sh
```

O script:

1. confere engine, ffmpeg e fixture
2. roda `vc.cli process sample_in.wav -o out/sample_out.wav` com os ganhos
   `--speech 100 --music 10 --bg 10` (preset "podcast")
3. valida que a saída tem a mesma duração (6s ± 0.1s) e sample rate do input
4. valida que a saída não saiu estourada nem em silêncio, via
   `ffmpeg ... volumedetect` (`max_volume` em dBFS; tolerância entre
   -50 e -0.5)

Se qualquer check falhar, o script sai com código 1 e a mensagem do problema
no stderr.

## Trocando o fixture

Se quiser usar outro áudio de teste, sobrescreva `sample_in.wav` mantendo
WAV mono 48 kHz. WAVs estéreo também funcionam (o engine faz downmix), mas
o smoke valida que o SR de saída bate com o de entrada, então mantenha a
configuração consistente.
