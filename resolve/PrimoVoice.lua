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

-- ---------------------------------------------------------------------------
-- JSON: tenta cjson, depois json, depois dkjson. Fallback gracioso se
-- nenhum estiver (vai dar erro no engine call, mas o painel ainda abre).
-- ---------------------------------------------------------------------------
local json
local json_lib = nil
for _, name in ipairs({"cjson.safe", "cjson", "json", "dkjson"}) do
    local ok, lib = pcall(require, name)
    if ok and lib then json = lib; json_lib = name; break end
end
if not json then
    -- Sem JSON disponivel: parsing manual basico (decode soh objetos simples).
    -- Funciona pq o engine soh emite {"chave": "valor" ou numero} por linha.
    function json.decode(s)
        local out = {}
        s = s:gsub("^%s*{%s*", ""):gsub("%s*}%s*$", "")
        for pair in s:gmatch("[^,]+") do
            local k, v = pair:match('^%s*"(.-)"%s*:%s*(.-)%s*$')
            if k then
                if v:match('^".*"$') then
                    out[k] = v:match('^"(.*)"$')
                elseif v:match('^%-?%d+%.?%d*$') then
                    out[k] = tonumber(v)
                else
                    out[k] = v
                end
            end
        end
        return out
    end
    function json.encode(t) return "" end
    json_lib = "fallback-parser"
end

-- ---------------------------------------------------------------------------
-- Localizacao do engine (venv) relativo a este arquivo.
-- ---------------------------------------------------------------------------
local HERE = (debug.getinfo(1, "S").source:sub(2)):match("(.*/)")
local PROJECT_ROOT = HERE:gsub("/resolve/$", "")
local ENGINE_DIR = PROJECT_ROOT .. "/engine"
local VENV_PY = ENGINE_DIR .. "/.venv/bin/python"

local function log(msg)
    -- Resolve Console (F6) captura stdout.
    print("[PrimoVoice] " .. tostring(msg))
end

local function engine_available()
    local f = io.open(VENV_PY, "r")
    if f then f:close(); return true end
    return false
end

-- Roda `python -m vc.cli <args>` no venv. Faz stream das linhas JSON de stdout
-- e chama on_line(evt) pra cada evento. Retorna (exit_code, last_event).
local function run_engine(args, on_line)
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
    -- Em Lua scripts do menu Workspace > Scripts, `resolve` é injetado como
    -- global. Não usar _G.resolve (alguns bindings injetam em outro table).
    return resolve
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
        -- Busy-wait 0.5s. Não tem sleep direto no Lua do Resolve.
        local t0 = os.time()
        while os.time() == t0 do end
    end
    local candidate = out_dir .. "/primovoice_in.wav"
    local f = io.open(candidate, "r")
    if f then f:close(); return candidate end
    -- Procura o arquivo no dir (Resolve às vezes renomeia).
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

local function _rename_clip(item, name)
    pcall(function() item:SetClipProperty("Clip Name", name) end)
end

local function import_result(project, in_wav, out_wav, keep_original)
    local media_pool = project:GetMediaPool()
    local timeline = project:GetCurrentTimeline()

    local items = media_pool:ImportMedia({tostring(out_wav)})
    if items and #items > 0 then
        local enh = items[1]
        _rename_clip(enh, "PrimoVoice · enhanced")
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
                _rename_clip(orig, "PrimoVoice · original")
                timeline:AddTrack("audio")
                media_pool:AppendToTimeline({orig})
            end
        end
    end
end

-- ---------------------------------------------------------------------------
-- UI (Fusion UIManager)
-- ---------------------------------------------------------------------------
local function build_ui()
    local r = get_resolve()
    if not r then
        log("erro: resolve nao disponivel (rode dentro do DaVinci).")
        return nil
    end
    log("resolve ok, pegando Fusion UIManager...")

    local fusion = r:Fusion()
    if not fusion then
        log("erro: r:Fusion() retornou nil")
        return nil
    end
    local ui = fusion.UIManager
    if not ui then
        log("erro: fusion.UIManager e nil")
        return nil
    end
    log("UIManager ok, montando janela...")

    -- bmd é o modulo global de UIDispatcher. Tenta varios nomes por seguranca.
    local disp_ctor
    if bmd and bmd.UIDispatcher then
        disp_ctor = bmd.UIDispatcher
    end
    if not disp_ctor then
        log("erro: bmd.UIDispatcher nao disponivel (globals: resolve=" ..
            tostring(resolve) .. ", fusion=" .. tostring(fusion) .. ")")
        return nil
    end

    local disp = disp_ctor(ui)

    local function slider_row(label, key, default)
        return ui:HGroup({
            ui:Label({Text = label, Weight = 0.3, MinimumSize = {90, 20}}),
            ui:Slider({ID = key, Weight = 0.5, Minimum = 0, Maximum = 100, Value = default}),
            ui:Label({ID = key .. "_val", Text = tostring(default) .. "%", Weight = 0.2, MinimumSize = {50, 20}}),
        })
    end

    local win
    local ok, err = pcall(function()
        win = disp:AddWindow({
            ID = "PrimoVoice", WindowTitle = "PrimoVoice", Geometry = {200, 200, 520, 580},
        }, {ui:VGroup({
            ui:Label({Text = "PrimoVoice — realce de voz", Weight = 0,
                      Font = ui:Font({PixelSize = 18, Bold = true})}),
            ui:Label({ID = "models_lbl", Text = "Verificando modelos…", Weight = 0}),
            ui:VGap(6),

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
            ui:Label({ID = "status", Text = "JSON: " .. (json_lib or "nil"), Weight = 0, WordWrap = true}),
        })})
    end)
    if not ok then
        log("erro no AddWindow: " .. tostring(err))
        return nil
    end
    return disp, win
end

local function main()
    log("PrimoVoice iniciando (json lib: " .. tostring(json_lib) .. ")")

    local disp, win = build_ui()
    if not disp or not win then
        log("build_ui falhou; abortando")
        return
    end
    log("janela criada, populando items...")

    local itm = win:GetItems()

    itm.backend:AddItem("Rápida (DeepFilterNet)")
    itm.backend:AddItem("Máxima (Resemble)")

    local PRESETS = presets_list()
    log("presets: " .. tostring(PRESETS and #PRESETS or 0))

    itm.preset:AddItem("Personalizado")
    if PRESETS then
        for _, p in ipairs(PRESETS) do
            local name = p.name or p.id or "?"
            itm.preset:AddItem(name)
        end
    end
    itm.preset.CurrentIndex = 0

    local function find_preset_idx(preset_id)
        if not PRESETS then return nil end
        for i, p in ipairs(PRESETS) do
            if p.id == preset_id then return i end
        end
        return nil
    end

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
            local mark
            if m.installed then mark = "✓"
            else mark = "⬇ " .. tostring(m.size_mb or "?") .. " MB" end
            parts[#parts + 1] = string.format("%s %s", m.name or m.id or "?", mark)
        end
        itm.models_lbl.Text = table.concat(parts, " · ")
    end

    local function on_close(ev) disp:ExitLoop() end
    win.On.PrimoVoice.Close = on_close

    win.On.process.Clicked = function(ev)
        local r = get_resolve()
        local project = r:GetProjectManager():GetCurrentProject()
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

        local tmp_name = os.tmpname() .. "_primovoice"
        os.execute("mkdir -p " .. tmp_name)

        itm.status.Text = "Renderizando áudio da timeline…"
        local in_wav = render_timeline_audio(project, tmp_name)
        if not in_wav then
            itm.status.Text = "Falha ao renderizar o áudio."
            return
        end
        local out_wav = tmp_name .. "/primovoice_out.wav"

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

    log("mostrando janela")
    win:Show()
    disp:RunLoop()
    win:Hide()
    log("loop terminou")
end

-- Wrap em pcall pra erros nao serem silenciosos.
local ok, err = pcall(main)
if not ok then
    log("ERRO FATAL: " .. tostring(err))
end
