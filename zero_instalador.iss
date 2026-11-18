; Instalador de Zero (Inno Setup 6 o 7). Requiere haber construido antes dist\Zero.exe:
;   py -m PyInstaller zero.spec --clean
;   & "C:\Program Files\Inno Setup 7\ISCC.exe" zero_instalador.iss
; Solo ASCII (sin acentos) para no depender de la codificacion del script.
; Instalacion POR USUARIO, sin administrador: el secreto de Microsoft queda en el Administrador de credenciales del
; usuario que instala (el mismo que luego ejecuta Zero).

#define NombreApp "Zero"
#define VersionApp "0.3.1"
#define PublicadorApp "Enlace"
#define EjecutableApp "Zero.exe"
#define DestinoSecreto "Zero.MicrosoftSecret"

[Setup]
AppId={{29BB7E08-39AC-42C0-9919-7455CF65DD09}
AppName={#NombreApp}
AppVersion={#VersionApp}
AppVerName={#NombreApp} {#VersionApp}
AppPublisher={#PublicadorApp}
DefaultDirName={userpf}\{#NombreApp}
DefaultGroupName={#NombreApp}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=instalador_salida
OutputBaseFilename={#NombreApp}_Setup_{#VersionApp}
SetupIconFile=assets\zero_icono.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[Files]
Source: "dist\{#EjecutableApp}"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
Name: "{userappdata}\{#NombreApp}"

[Icons]
Name: "{group}\{#NombreApp}"; Filename: "{app}\{#EjecutableApp}"; WorkingDir: "{app}"
Name: "{group}\{#NombreApp} - Simulacion (no envia nada)"; Filename: "{app}\{#EjecutableApp}"; Parameters: "--simular"; WorkingDir: "{app}"
Name: "{group}\Editar configuracion (.env)"; Filename: "notepad.exe"; Parameters: """{userappdata}\{#NombreApp}\.env"""
Name: "{group}\Desinstalar {#NombreApp}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#NombreApp}"; Filename: "{app}\{#EjecutableApp}"; WorkingDir: "{app}"; Tasks: desktopicon

[Code]
var
  PaginaMicrosoft: TInputQueryWizardPage;
  PaginaGraph: TInputQueryWizardPage;
  PaginaCarpeta: TInputDirWizardPage;

function EdgeInstalado(): Boolean;
begin
  Result :=
    FileExists(ExpandConstant('{commonpf32}\Microsoft\Edge\Application\msedge.exe')) or
    FileExists(ExpandConstant('{commonpf64}\Microsoft\Edge\Application\msedge.exe'));
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if not EdgeInstalado() then
    if MsgBox('No se encontro Microsoft Edge en este equipo.' + #13#10 + #13#10 +
              'Zero lo necesita para entrar al portal del SRI.' + #13#10 + #13#10 +
              'Desea continuar de todas formas?', mbConfirmation, MB_YESNO) = IDNO then
      Result := False;
end;

function SoloAscii(const Texto: string): Boolean;
var
  i: Integer;
begin
  Result := True;
  for i := 1 to Length(Texto) do
    if Ord(Texto[i]) > 127 then
      Result := False;
end;

function CarpetaPorDefecto(): string;
begin
  if DirExists('D:\') then
    Result := 'D:\Documentos\Zero'
  else
    Result := ExpandConstant('{userdocs}\Zero');
end;

procedure InitializeWizard;
begin
  PaginaMicrosoft := CreateInputQueryPage(wpSelectDir,
    'Microsoft Graph',
    'Acceso a los archivos de OneDrive',
    'El secreto se guarda en el Administrador de credenciales de Windows, no en un archivo. ' +
    'Si lo deja en blanco se conserva el que ya este guardado.');
  PaginaMicrosoft.Add('Tenant ID:', False);
  PaginaMicrosoft.Add('Client ID:', False);
  PaginaMicrosoft.Add('Secreto del cliente:', True);   { True = campo de contrasena }

  PaginaGraph := CreateInputQueryPage(PaginaMicrosoft.ID,
    'Archivos en OneDrive',
    'Identificadores del Control y del archivo de credenciales',
    'Si aun no los tiene, puede dejarlos en blanco y completarlos despues en el .env ' +
    '(hay un acceso directo en el menu inicio).');
  PaginaGraph.Add('Control - drive ID:', False);
  PaginaGraph.Add('Control - item ID:', False);
  PaginaGraph.Add('Credenciales - drive ID:', False);
  PaginaGraph.Add('Credenciales - item ID:', False);

  PaginaCarpeta := CreateInputDirPage(PaginaGraph.ID,
    'Carpeta de trabajo',
    'Donde se guardan los comprobantes y las evidencias',
    'Zero crea aqui las carpetas Declaraciones y Evidencias. Use una ruta sin acentos.',
    False, '');
  PaginaCarpeta.Add('');
  PaginaCarpeta.Values[0] := CarpetaPorDefecto();
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = PaginaMicrosoft.ID then
  begin
    if Pos('"', PaginaMicrosoft.Values[2]) > 0 then
    begin
      MsgBox('El secreto no puede contener comillas dobles.', mbError, MB_OK);
      Result := False;
    end;
  end
  else if CurPageID = PaginaCarpeta.ID then
  begin
    if (Trim(PaginaCarpeta.Values[0]) = '') or (not SoloAscii(PaginaCarpeta.Values[0])) then
    begin
      MsgBox('Indique una carpeta de trabajo sin acentos ni caracteres especiales.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

procedure GuardarSecreto(const Secreto: string);
var
  Codigo: Integer;
begin
  if Secreto = '' then
    Exit;
  if (not Exec(ExpandConstant('{sys}\cmdkey.exe'),
        '/generic:{#DestinoSecreto} /user:zero /pass:"' + Secreto + '"',
        '', SW_HIDE, ewWaitUntilTerminated, Codigo)) or (Codigo <> 0) then
    MsgBox('No se pudo guardar el secreto en el Administrador de credenciales.' + #13#10 +
           'Guardelo despues con: cmdkey /generic:{#DestinoSecreto} /user:zero /pass:<secreto>',
           mbError, MB_OK);
end;

procedure EscribirEnv();
var
  RutaConfig, RutaEnv, Carpeta: string;
  Env: TStringList;
begin
  RutaConfig := ExpandConstant('{userappdata}\{#NombreApp}');
  ForceDirectories(RutaConfig);
  RutaEnv := RutaConfig + '\.env';
  { Solo si NO existe: al reinstalar o actualizar no se pisa la configuracion real. }
  if FileExists(RutaEnv) then
    Exit;
  Carpeta := Trim(PaginaCarpeta.Values[0]);
  ForceDirectories(Carpeta);
  StringChangeEx(Carpeta, '\', '/', True);  { el .env usa barras / y sin comillas }
  Env := TStringList.Create;
  try
    Env.Add('# Generado durante la instalacion de {#NombreApp} {#VersionApp}. El secreto NO esta aqui.');
    Env.Add('DRY_RUN=false');
    Env.Add('SRI_LOGIN_URL=https://srienlinea.sri.gob.ec/sri-en-linea/SriDeclaraciones/Publico/declaraciones');
    Env.Add('ZERO_DOCS=' + Carpeta);
    Env.Add('MICROSOFT_TENANT_ID=' + Trim(PaginaMicrosoft.Values[0]));
    Env.Add('MICROSOFT_CLIENT_ID=' + Trim(PaginaMicrosoft.Values[1]));
    Env.Add('MICROSOFT_SECRET_TARGET={#DestinoSecreto}');
    Env.Add('GRAPH_CONTROL_DRIVE_ID=' + Trim(PaginaGraph.Values[0]));
    Env.Add('GRAPH_CONTROL_ITEM_ID=' + Trim(PaginaGraph.Values[1]));
    Env.Add('GRAPH_CREDENCIALES_DRIVE_ID=' + Trim(PaginaGraph.Values[2]));
    Env.Add('GRAPH_CREDENCIALES_ITEM_ID=' + Trim(PaginaGraph.Values[3]));
    Env.SaveToFile(RutaEnv);
  finally
    Env.Free;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    GuardarSecreto(PaginaMicrosoft.Values[2]);
    EscribirEnv();
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Codigo: Integer;
begin
  { El .env y los datos se conservan; el secreto se retira del Administrador de credenciales. }
  if CurUninstallStep = usUninstall then
    Exec(ExpandConstant('{sys}\cmdkey.exe'), '/delete:{#DestinoSecreto}', '', SW_HIDE, ewWaitUntilTerminated, Codigo);
end;
