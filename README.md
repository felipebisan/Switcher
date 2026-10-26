# Mapa e telemetria em grupo

Arquivos do aplicativo: `g29_switcher.py`, `g29_map.py`, `g29_roadmap.py`, `g29_minimap.py` e a pasta `map_assets` devem ficar juntos. O mapa usa Pillow, já utilizado pelo aplicativo; não exige bibliotecas adicionais.

## Minimap transparente

O estilo padrão agora é **Transparent minimap**: ruas claras e marcadores sobre fundo realmente transparente, sem terreno, moldura, círculo branco, título ou rodapé. Há um esmaecimento suave nas extremidades. A janela deixa os cliques passarem e não recebe foco. O mapa aparece quando há posição válida sua ou dos participantes do grupo.

Na primeira abertura desta versão, o raio passa a no mínimo **1.000 m**, oferecendo uma visão quatro vezes mais afastada que a configuração anterior de 250 m. As opções **Show panel** e de posicionamento são preservadas. Se o mapa estava desativado, ative **Map → Show panel**. Mudanças posteriores de zoom são lembradas normalmente.

- **Rotate with car**: gira suavemente o mapa usando a direção do deslocamento; ao parar, mantém a última direção. Desative para manter o norte no topo. Em marcha a ré, a direção acompanha o deslocamento.
- **Show player names**: mostra os nomes dos amigos. Sua seta fica branca e os outros participantes têm marcadores coloridos.
- **Map style → Dark / Original**: permite voltar aos estilos anteriores.

A calibração existente é reutilizada. O desenho das ruas foi vetorizado a partir das suas capturas e está em `map_assets/roads.json`; não usa o mapa do Wand. Edificações e terreno foram filtrados. Trechos pouco visíveis, encobertos, estradas de terra coloridas e áreas não capturadas podem ficar ausentes: esta é uma extração visual das ruas, não a malha oficial do jogo.

Os estilos Dark e Original mostram as seis capturas fornecidas, encaixadas em uma superfície de 2494 × 3156 pixels. As imagens originais são preservadas e também são usadas para calibrar. Máscaras escondem elementos da interface e a rota azul, aproveitando outras capturas nas sobreposições. Regiões sem cobertura permanecem vazias; ruas encobertas sem uma segunda captura não são inventadas.

Após a calibração, o painel acompanha o carro e mostra até 16 participantes. Dark e Original também mostram distâncias em linha reta. Antes da calibração, esses estilos apresentam uma visão geral; o transparente mostra um aviso de calibração quando há telemetria. Não são colocados marcadores em posições não verificadas.

## Calibrar as ruas com a posição do carro

1. Reinicie o aplicativo e pare o carro em um cruzamento fácil de reconhecer. Confirme que a telemetria continua funcionando.
2. Abra **Map → Calibrate road map...** e clique em **Capture position**. O aplicativo retém a última posição válida por até dois minutos para permitir alternar entre o jogo e a janela.
3. Aproxime a imagem com a roda do mouse; arraste com o botão direito para navegar. Clique com o botão esquerdo no lugar exato onde o carro está.
4. Feche a janela, vá a outro cruzamento distante e repita. Os pontos provisórios ficam disponíveis ao reabrir a janela, enquanto o aplicativo continuar aberto.
5. Faça isso em pelo menos **três lugares bem separados**, formando um triângulo amplo; quatro são recomendados. Pontos numa única rua reta não permitem uma calibração confiável.
6. Clique em **Save calibration** e confira o alinhamento em um quarto lugar. Para corrigir um ponto, use **Undo point**; **Clear points** limpa os pontos da edição. A calibração anterior só é substituída quando uma nova é salva com sucesso.

O resultado fica em `map_calibration.json`. Ele pode ser copiado para a pasta do aplicativo dos amigos que usam as mesmas imagens; assim não precisam repetir a calibração. O código não adivinha coordenadas a partir das capturas. A calibração real ainda precisa ser feita dentro do jogo.

## Menu Map

- **Show panel**: exibe ou oculta o painel. Ocultar não encerra o compartilhamento.
- **Position**: Bottom center, Center, Top center, Bottom left ou Bottom right.
- **View radius**: 250, 500, 1000 ou 2000 metros; valores menores aproximam a imagem.
- **Map style**: Transparent minimap, Dark ou Original.
- **Show trails**: liga o rastro opcional, inicialmente desativado.
- **Calibrate road map...**: alinha as imagens às coordenadas do jogo.
- **Save trail...**: exporta seu trajeto recente em JSON (até 800 pontos). O arquivo exportado não é carregado automaticamente.
- **Clear trail**: apaga os trajetos da visualização atual.
- **Host group... / Join group...**: cria ou entra em um grupo.
- **Group details...**: mostra o endereço informado, porta e código da conexão.
- **Leave group**: encerra o compartilhamento. Se o anfitrião sair ou fechar o programa, o grupo fica sem servidor.

As preferências do mapa são salvas em `map_config.json`. O código do grupo não é salvo e nenhuma conexão é retomada automaticamente ao abrir o programa.

## Jogar em grupo

1. Todos executam a nova versão e mantêm o Data Out do jogo configurado para `127.0.0.1`, porta `5300`.
2. Um participante abre **Map → Host group...**, escolhe o nome e mantém a porta de grupo `5301`. O app gera um código privado que pode ser copiado.
3. O anfitrião compartilha seu endereço IPv4 da rede local ou VPN, a porta e o código. O endereço `127.0.0.1` só serve para a conexão interna do anfitrião, não para os amigos.
4. Os amigos abrem **Map → Join group...** e preenchem essas informações.
5. Todos devem estar na mesma sessão/mundo do jogo. O programa não consegue confirmar a sessão pela telemetria.

Em computadores de casas diferentes, usem uma VPN que permita comunicação entre participantes. O código identifica e autentica o grupo; a criptografia do tráfego depende da VPN. Não há servidor público incluído. No anfitrião, o firewall precisa permitir a porta UDP escolhida na rede utilizada; o aplicativo não altera o firewall automaticamente.

O painel indica quando recebe resposta do anfitrião. Se permanecer em “Waiting for host”, confira endereço, porta, código, VPN/firewall e os relógios dos computadores (diferença máxima de um minuto).

Quando o jogo pausa ou para de enviar posição válida, o marcador desaparece. Participantes desconectados são removidos em cerca de três segundos. Saltos grandes de posição interrompem o traçado para não desenhar uma linha de viagem rápida. O mapa usa os eixos X/Z com orientação fixa; a seta segue o deslocamento e não a orientação do carro quando parado.

## Compilar novamente

Com os quatro arquivos Python, a pasta `map_assets` (incluindo `roads.json`) e os ícones na pasta `C:\G29`, use:

```cmd
cd C:\G29
python -m PyInstaller --clean --onefile --windowed --name "G29 Mode Switcher" --icon="g29_exe.ico" --add-data="g29_tray.ico;." --add-data="map_assets;map_assets" --hidden-import=pystray._win32 g29_switcher.py
```

Os imports incluem os módulos de mapa no executável; a opção adicional inclui as capturas. Uma pasta `map_assets` ao lado do executável tem preferência sobre as imagens empacotadas. A calibração e as preferências ficam ao lado do executável. Reinicie a versão em execução para carregar as mudanças. O executável anterior não é atualizado pela alteração dos arquivos Python.

## Automatic alignment and low-latency minimap

Map > Automatic alignment loads the bundled profile for this Japan map automatically. The profile comes from the previously validated calibration and the vector alignment; it is not live road snapping or a new survey of the game. It works without manually capturing landmarks. Uncheck it to use the saved manual calibration; choosing Calibrate road map also switches to manual mode. The saved manual file is preserved.

The local car heading now comes from telemetry Yaw, including while stationary, drifting or reversing. The map aims for 30 updates per second, subtracting drawing time from the interval. Road layers are cached per zoom to avoid rebuilding all road geometry every frame. The first frame after a zoom change builds the cache and may pause briefly. Group players still use the existing network update rate and movement-derived headings.

Restart the Python app, or rebuild the executable with the existing command including map_assets. Check alignment and heading during actual driving; automated checks do not replace in-game validation.

## Alignment correction for the 250 m view

Automatic alignment revision 2 replaces the earlier screenshot-based manual profile with the world-to-map calibration published in Scenic Navigator static/nav_logic.js, composed with static/routing.js labToMapPixel and this app's vector-to-atlas registration. This corrects translation, scale and skew consistently at every zoom. It does not snap the car to a nearby road. Manual calibration files remain unchanged.
Sources:
https://github.com/atikhobaev/fh6-scenic-navigator/blob/main/static/nav_logic.js
https://github.com/atikhobaev/fh6-scenic-navigator/blob/main/static/routing.js

Keep Map > Automatic alignment enabled and restart the application to load the corrected profile. In-game accuracy still needs verification, especially at tunnels, multilayer roads and locations where the source road geometry may be approximate.

## Fine-tune a remaining road offset

Stop at the center of an identifiable intersection, open Map > Fine-tune alignment..., then use Capture position. In the north-up road view, the blue cross is the reported position. Click the same intersection where the car is stopped and Apply. Use Zoom to distinguish nearby branches. The saved translation applies to every zoom level while Automatic alignment is enabled. Reset adjustment removes only this translation. Full manual calibration remains available for scale/rotation errors. This operation uses a fixed captured position, not a moving live marker; recapture after moving. Corrections larger than 100 m are rejected. Source road geometry can contain local errors, so verify at another intersection too.

The application also requires g29_alignment.py alongside its other Python modules. PyInstaller includes it through the normal import.

## Instrument panel

Choose Map > Map style > Instrument panel to combine the tachometer, current gear, speedometer and road map in one 860 x 300 overlay. Map > Position and View radius remain available. Map > Show panel enables/disables the complete panel. Other map styles are preserved.

While the instrument panel is enabled, the separate telemetry HUD is hidden. Changing back to a previous map style restores the HUD according to its existing preference. The panel reads actual local RPM, RPM limit, speed and gear; it does not display simulated fuel, temperature or other unavailable values. Group markers and map alignment are preserved.

The Python application now also requires g29_dashboard.py. Restart the application or rebuild the executable with the existing PyInstaller command; normal imports include the new modules. The panel stays hidden when no usable map position is available. Native overlay dimensions adapt to the selected presentation.

## Transparent panel and size

The instrument panel now defaults to a transparent background, including the inside of its dials. Toggle Map > Transparent panel background to restore the dark panel. Map > Panel size offers 50%, 75%, 100%, 125%, 150% and 200%; 100% is 860 x 300. Size and background are saved. Scaling preserves proportions and automatically fits the available screen. Map > View radius remains independent and changes the geographic zoom only. Restart the app after updating, or rebuild your executable.

## Dial backgrounds, smooth pointers and lower positioning

Map > Dark dial backgrounds restores the original dark fill inside the RPM and speed dials only. Leave Transparent panel background enabled to keep the surrounding area transparent; uncheck Dark dial backgrounds for fully transparent dials. Both choices are saved.

The panel animation targets 60 Hz and the map renders on one background worker, with at most one pending map frame. Dial graphics and the composited map are cached. Needles use a short 45 ms time-constant filter without overshoot; digital readings and gear remain immediate. Actual frame rate depends on hardware, panel size and game load. Bottom center now uses a 12 px bottom margin instead of 95 px.

## Unified Telemetry menu

Telemetry is now the single top-level entry for display options:
- Map: Show map, View radius, Rotate with car, Alignment and Trail.
- Instruments: Show instruments and Dark dial backgrounds.
- Layout: Position and Instrument size.
- Compact HUD: the original compact RPM/speed/gear HUD and its position settings.

Show map and Show instruments are independent and saved. Enable both for the combined panel, only Map for the minimap, or only Instruments for two adjacent dials. The outside background is always transparent, even with older saved opaque settings. Dark dial backgrounds only affects the inside of the dials. Friend/group sharing and player-name controls are removed from the menu. Old display preferences migrate automatically. Restart the app or rebuild the executable.

## Interface de configurações
A janela MODE SWITCHER abre após os créditos. Na bandeja, use Open app... para reabri-la.
Driving reúne modos e configuração do volante; Map contém zoom, orientação, alinhamento e trilha; Instruments controla os mostradores e o HUD compacto; Layout reúne posição, tamanho e aparência. As configurações são salvas automaticamente. Fechar a janela mantém o aplicativo na bandeja.
A interface usa o preto e azul dos créditos e cantos arredondados quando suportados pelo Windows. O novo módulo g29_interface.py deve ficar junto de g29_switcher.py; o PyInstaller o inclui pelo import.

## Interface simplificada
A interface agora possui Configuration, Telemetry e About, sem barra de rolagem.
Configuration configura rotação RACE/DRIFT e botão, permite ocultar o indicador e desativar comandos de rotação (mantendo a última rotação aplicada).
Telemetry possui Instruments (Panel with map / Panel only / Disabled), Compact e Map. Compact e Map ficam bloqueados enquanto Instruments está ativo; as preferências são preservadas. Cada HUD tem posição independente, salva automaticamente.
A bandeja oferece Open app... e Exit. Zoom e alinhamento do mapa integrado ficam em Instruments; o mapa independente tem seus controles em Map.

## Switcher & HUD
Nome atualizado na interface, créditos e bandeja. Instruments, Compact e Map possuem tamanhos 50%, 75% e 100%. Tamanhos antigos maiores dos instrumentos voltam a 100%.
Nesta atualização, o mapa independente passa ao canto inferior esquerdo e o compacto ao inferior direito uma única vez; mudanças posteriores são preservadas. O novo módulo g29_compact_layout.py deve acompanhar os demais arquivos.
Para gerar o executável com o nome novo, use --name "Switcher & HUD" no comando PyInstaller.
