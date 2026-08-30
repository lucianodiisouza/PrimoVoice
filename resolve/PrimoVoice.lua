--[[
    PrimoVoice - voice enhancement for DaVinci Resolve (Lua port).

    Resolve 21 no macOS soh tem LuaJIT (sem Python embed), entao o painel
    roda em Lua. O engine em si (deepfilter + demucs + remix) continua
    sendo Python - este script soh chama via subprocess.

    Fluxo do botao "Processar":
      1. renderiza o audio da timeline (faixa/intervalo atual) para WAV
      2. chama o engine (isola voz -> separa -> remixa com os ganhos)
      3. importa o WAV limpo de volta numa nova faixa de audio
         (com A/B ligado, importa o original ao lado pra comparar mute/solo)
]]

local json = require("json")  -- cjson/json vem com o LuaJIT do Resolve

-- ---------------------------------------------------------------------------
-- Localizacao do engine (venv) relativo a este arquivo.
-- ---------------------------------------------------------------------------
local HERE = (debug.getinfo(1, "S").source:sub(2)):match("(.*/)")
local PROJECT_ROOT = HERE:gsub("/resolve/$", "")
local ENGINE_DIR = PROJECT_ROOT .. "/engine"
local VENV_PY = ENGINE_DIR .. "/.venv/bin/python"

local function engine_available()
    local f = io.open(VENV_PY, "r")
    if f then f:close(); return true end
    return false
end

-- Roda `python -m vc.cli <args>` no venv. Faz stream das linhas JSON de stdout
-- e chama on_line(evt) pra cada evento. Retorna (exit_code, last_event).
local function run_engine(args, on_line)
    -- Argumentos precisam de shell-escape basico. Como soh vem de UI, eh
    -- seguro usar string.format direto.
    local cmd_parts = {VENV_PY, "-m", "vc.cli"}
    for _, a in ipairs(args) do cmd_parts[#cmd_parts + 1] = a end
    local cmd = table.concat(cmd_parts, " ")
    local p = io.popen(cmd .. " 2>&1", "r")
    if not p then return -1, nil end

    local last = nil
    for line in p:lines() do
        if line and line ~= "" then
            local ok, evt = pcall(json.decode, line)
            if not ok or type(evt) ~= "table" then
                evt = {log = line}
            end
            last = evt
            if on_line then on_line(evt) end
        end
    end
    p:close()
    return 0, last
end

local function models_status()
    if not engine_available() then return {} end
    local cmd = VENV_PY .. " -m vc.cli models"
    local p = io.popen(cmd .. " 2>/dev/null", "r")
    if not p then return {} end
    local out = p:read("*a")
    p:close()
    if not out or out == "" then return {} end
    local ok, decoded = pcall(json.decode, out)
    if not ok then return {} end
    return decoded
end

local function presets_list()
    if not engine_available() then return {} end
    local cmd = VENV_PY .. " -m vc.cli presets"
    local p = io.popen(cmd .. " 2>/dev/null", "r")
    if not p then return {} end
    local out = p:read("*a")
    p:close()
    if not out or out == "" then return {} end
    local ok, decoded = pcall(json.decode, out)
    if not ok then return {} end
    return decoded
end

-- ---------------------------------------------------------------------------
-- Resolve API
-- ---------------------------------------------------------------------------
local function get_resolve()
    -- Lua: resolve e global injetado pelo Resolve, sem import.
    return _G.resolve
end

local function render_timeline_audio(project, out_dir)
    project:SetCurrentRenderFormatAndCodec("wav", "LinearPCM")
    project:SetRenderSettings({
        TargetDir = out_dir,
        CustomName = "primovoice_in",
        ExportVideo = false,
        ExportAudio = true,
    })
    local job_id = project:AddRenderJob()
    project:StartRendering({job_id}, false)
    while project:IsRenderingInProgress() do
        -- sleep em segundos. Fusion Lua nao tem sleep direto - usa o clock
        -- do host. Um loop simples de busy-wait com os.time funciona.
        local t0 = os.time()
        while os.time() == t0 do end
    end
    -- Resolve coloca a extensao do container.
    local candidate = out_dir .. "/primovoice_in.wav"
    local f = io.open(candidate, "r")
    if f then f:close(); return candidate end
    -- Tenta achar o arquivo no diretorio (Resolve pode usar outro nome).
    local p = io.popen("ls " .. out_dir .. " 2>/dev/null")
    if not p then return nil end
    for name in p:lines() do
        if name:sub(1, 15) == "primovoice_in" then
            p:close()
            return out_dir .. "/" .. name
        end
    end
    p:close()
    return nil
end

local function _rename_clip(media_pool, item, name)
    -- SetClipProperty aceita "Clip Name". No Lua, item:SetClipProperty(...).
    pcall(function() item:SetClipProperty("Clip Name", name) end)
end

local function import_result(project, in_wav, out_wav, keep_original)
    local media_pool = project:GetMediaPool()
    local timeline = project:GetCurrentTimeline()

    local items = media_pool:ImportMedia({tostring(out_wav)})
    if items and #items > 0 then
        local enh = items[1]
        _rename_clip(media_pool, enh, "PrimoVoice · enhanced")
        timeline:AddTrack("audio")
        media_pool:AppendToTimeline({enh})
    end

    if keep_original and in_wav then
        local f = io.open(tostring(in_wav), "r")
        if f then
            f:close()
            local orig_items = media_pool:ImportMedia({tostring(in_wav)})
            if orig_items and #orig_items > 0 then
                local orig = orig_items[1]
                _rename_clip(media_pool, orig, "PrimoVoice · original")
                timeline:AddTrack("audio")
                media_pool:AppendToTimeline({orig})
            end
        end
    end
end

-- ---------------------------------------------------------------------------
-- UI (Fusion UIManager)
-- ---------------------------------------------------------------------------
local function main()
    local resolve = get_resolve()
    if not resolve then
        print("Erro: rode este script de dentro do DaVinci Resolve (Workspace ▸ Scripts).")
        return
    end

    local fusion = resolve:Fusion()
    local ui = fusion.UIManager
    local disp = bmd.UIDispatcher(ui)

    local function slider_row(label, key, default)
        return ui:HGroup({
            ui:Label({Text = label, Weight = 0.3, MinimumSize = {90, 20}}),
            ui:Slider({ID = key, Weight = 0.5, Minimum = 0, Maximum = 100, Value = default}),
            ui:Label({ID = key .. "_val", Text = tostring(default) .. "%", Weight = 0.2, MinimumSize = {50, 20}}),
        })
    end

    local win = disp:AddWindow({
        ID = "PrimoVoice", WindowTitle = "PrimoVoice", Geometry = {200, 200, 520, 560},
    }, {ui:VGroup({
        ui:Label({Text = "PrimoVoice — realce de voz", Weight = 0,
                  Font = ui:Font({PixelSize = 18, Bold = true})}),
        ui:Label({ID = "models_lbl", Text = "Verificando modelos…", Weight = 0}),
        ui:VGap(6),

        -- Preset
        ui:HGroup({
            ui:Label({Text = "Preset:", Weight = 0.3, MinimumSize = {90, 20}}),
            ui:ComboBox({ID = "preset", Weight = 0.7}),
        }),
        ui:Label({ID = "preset_desc", Text = " ", Weight = 0, WordWrap = true}),
        ui:VGap(6),

        slider_row("Speech", "speech", 100),
        slider_row("Music", "music", 10),
        slider_row("Background", "bg", 10),
        ui:VGap(6),

        ui:HGroup({
            ui:Label({Text = "Qualidade da voz:", Weight = 0.4}),
            ui:ComboBox({ID = "backend", Weight = 0.6}),
        }),
        ui:CheckBox({ID = "separate", Text = "Separar música/fundo (Demucs)", Checked = true}),
        ui:CheckBox({ID = "ab", Text = "Manter original na timeline (A/B)", Checked = true}),
        ui:VGap(8),
        ui:Button({ID = "process", Text = "Processar timeline"}),
        ui:Label({ID = "status", Text = "", Weight = 0, WordWrap = true}),
    })})

    local itm = win:GetItems()

    -- Combobox: qualidade da voz
    itm.backend:AddItem("Rápida (DeepFilterNet)")
    itm.backend:AddItem("Máxima (Resemble)")

    -- Combobox: presets
    local PRESETS = presets_list()
    itm.preset:AddItem("Personalizado")
    if PRESETS then
        for _, p in ipairs(PRESETS) do
            itm.preset:AddItem(p.name or p.id)
        end
    end
    itm.preset.CurrentIndex = 0

    local function apply_preset(idx)
        if not PRESETS or idx <= 0 or idx > #PRESETS then
            itm.preset_desc.Text = "Ajusta os sliders à mão; o painel não sobrescreve."
            return
        end
        local p = PRESETS[idx]
        itm.speech.Value = p.speech or 100
        itm.music.Value = p.music or 10
        itm.bg.Value = p.background or 10
        itm.backend.CurrentIndex = (p.enhance_backend == "resemble") and 1 or 0
        itm.separate.Checked = (p.do_separate ~= false)
        itm.speech_val.Text = tostring(math.floor(itm.speech.Value)) .. "%"
        itm.music_val.Text = tostring(math.floor(itm.music.Value)) .. "%"
        itm.bg_val.Text = tostring(math.floor(itm.bg.Value)) .. "%"
        itm.preset_desc.Text = p.description or ""
    end

    -- Slider changes -> mark "Personalizado"
    for _, key in ipairs({"speech", "music", "bg"}) do
        win.On[key].ValueChanged = function(ev)
            itm[key .. "_val"].Text = tostring(math.floor(itm[key].Value)) .. "%"
            if itm.preset.CurrentIndex ~= 0 then
                itm.preset.CurrentIndex = 0
                itm.preset_desc.Text = "Personalizado — ajusta os sliders à mão."
            end
        end
    end

    win.On.preset.CurrentIndexChanged = function(ev)
        apply_preset(itm.preset.CurrentIndex)
    end

    -- Status dos modelos
    local mods = models_status()
    if not mods or #mods == 0 then
        itm.models_lbl.Text = "⚠ Engine não instalado — rode engine/setup.sh"
    else
        local parts = {}
        for _, m in ipairs(mods) do
            local mark = m.installed and "✓" or ("⬇ " .. tostring(m.size_mb) .. " MB")
            parts[#parts + 1] = string.format("%s %s", m.name or m.id, mark)
        end
        itm.models_lbl.Text = table.concat(parts, " · ")
    end

    local function on_close(ev)
        disp:ExitLoop()
    end
    win.On.PrimoVoice.Close = on_close

    win.On.process.Clicked = function(ev)
        local project = resolve:GetProjectManager():GetCurrentProject()
        if not project or not project:GetCurrentTimeline() then
            itm.status.Text = "Abra um projeto com uma timeline."
            return
        end
        local backend = (itm.backend.CurrentIndex == 1) and "resemble" or "deepfilter"
        local preset_idx = itm.preset.CurrentIndex
        local preset_id = nil
        if PRESETS and preset_idx > 0 and preset_idx <= #PRESETS then
            preset_id = PRESETS[preset_idx].id
        end

        -- Diretorio temporario
        local tmp = os.tmpname() .. "_primovoice"
        os.execute("mkdir -p " .. tmp)

        itm.status.Text = "Renderizando áudio da timeline…"
        local in_wav = render_timeline_audio(project, tmp)
        if not in_wav then
            itm.status.Text = "Falha ao renderizar o áudio."
            return
        end
        local out_wav = tmp .. "/primovoice_out.wav"

        local args
        if preset_id then
            args = {"process", in_wav, "-o", out_wav, "--preset", preset_id}
        else
            args = {
                "process", in_wav, "-o", out_wav,
                "--speech", tostring(math.floor(itm.speech.Value)),
                "--music", tostring(math.floor(itm.music.Value)),
                "--bg", tostring(math.floor(itm.bg.Value)),
                "--enhance", backend,
            }
        end
        if not itm.separate.Checked then
            args[#args + 1] = "--no-separate"
        end

        local function on_line(evt)
            if evt and evt.progress then
                itm.status.Text = evt.progress
            end
        end

        local code = run_engine(args, on_line)
        if code ~= 0 then
            itm.status.Text = "Erro no processamento (ver console)."
            return
        end
        local keep_original = itm.ab.Checked
        import_result(project, in_wav, out_wav, keep_original)
        if keep_original then
            itm.status.Text = "Pronto — duas faixas adicionadas. Mute/solo 'PrimoVoice · enhanced' vs '· original' pra A/B."
        else
            itm.status.Text = "Pronto — nova faixa de áudio adicionada."
        end
    end

    win:Show()
    disp:RunLoop()
    win:Hide()
end

if not pcall(main) then
    print("PrimoVoice error: " .. tostring(...))
end
