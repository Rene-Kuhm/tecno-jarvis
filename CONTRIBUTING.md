# Contribuir a Tecno--J.A.R.V.I.S

Gracias por querer mejorar Tecno--J.A.R.V.I.S. Este proyecto controla audio, pantalla, archivos, navegador y acciones del sistema; por eso cada cambio debe ser chico, verificable y respetar lo que ya funciona.

## Regla principal

No rompas la experiencia existente: instalacion, arranque, UI, voz, configuracion y releases deben seguir funcionando despues de cada cambio.

## Flujo obligatorio

1. Crea una rama desde `main` actualizada.
2. Haz un cambio con un solo proposito.
3. No subas secretos, `.venv`, caches, logs ni archivos generados.
4. Ejecuta las verificaciones de esta guia.
5. Abre un Pull Request con descripcion clara, capturas si toca UI y checklist completo.

## Branding

| Lugar | Texto correcto |
|-------|----------------|
| App, instaladores, runners y README principal | `Tecno--J.A.R.V.I.S` |
| Agencia y footer permitido | `TecnoDespegue` |
| Sitio web | `https://www.tecnodespegue.com` |

No uses nombres antiguos, marcas internas ni referencias a proyectos previos.

## Instalacion y ejecucion

El instalador debe seguir siendo la puerta de entrada para usuarios nuevos.

Antes de enviar cambios que toquen instalacion, dependencias o arranque, verifica:

```bat
python -m py_compile install.py setup.py
python install.py --check
```

Si tocaste dependencias o instaladores, prueba una carpeta limpia sin `.venv` ni `config/api_keys.json`.

## UI y capturas

Si cambias `ui.py`, preserva la funcionalidad existente. No elimines paneles, diagnosticos, carga de archivos, comandos ni estado realtime sin explicarlo en el PR.

Para cambios visuales:

- Incluye captura antes/despues si el cambio es visible.
- Las capturas del README deben mostrar solo la ventana de Tecno--J.A.R.V.I.S.
- No subas capturas donde aparezcan escritorio, claves, datos personales u otras apps.

## Seguridad

Nunca subas:

- `config/api_keys.json`
- `.venv/`
- `__pycache__/`
- `*.pyc`
- Logs locales
- `memory/session_state.json`
- API keys, tokens, credenciales o rutas privadas innecesarias

## Verificacion minima

Ejecuta lo que aplique antes de pedir review:

```bat
python -m py_compile main.py ui.py install.py setup.py
python install.py --check
```

Para dependencias criticas:

```bat
.venv\Scripts\python.exe -c "import PyQt6, sounddevice, cv2, numpy, psutil, playwright, pyautogui; print('imports-ok')"
```

Para probar ejecucion en Windows:

```bat
run.bat
```

## Commits

Usa Conventional Commits:

```text
feat(ui): add holographic status rail
fix(install): generate launchers during setup
docs(readme): update installation guide
```

Cada commit debe tener un motivo claro. No mezcles rediseño de UI, instalador y documentacion en el mismo commit salvo que formen una sola entrega.

## Checklist antes del PR

- [ ] Mi rama nace desde `main` actualizada.
- [ ] El cambio tiene un solo proposito.
- [ ] No subi secretos ni archivos generados.
- [ ] Compile los archivos Python afectados.
- [ ] Ejecute `python install.py --check` si toque instalacion o docs de instalacion.
- [ ] Probe la app o explique por que no pude probarla.
- [ ] Inclui capturas si toque UI.
- [ ] Respete branding: `Tecno--J.A.R.V.I.S` y `TecnoDespegue` donde corresponde.
- [ ] Actualice README/release notes si cambia la experiencia del usuario.

## Criterio de rechazo

Un PR puede rechazarse si rompe instalacion, cambia branding incorrectamente, mezcla demasiados temas, no explica como fue probado, elimina funcionalidad existente sin justificacion o introduce secretos/archivos locales.
