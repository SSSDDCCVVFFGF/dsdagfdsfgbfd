Setup

1. Datein runterladen und sich bei https://railway.com/ anmelden zum hosten
   
2. ersttellt ein bot bei @botfather und erstellt 3 gruppen
   kopiert den Bot Token 
   hinzufügt den bot zu allen gruppen und gibt ihm alle rechte auch neue admins hinzufügen
   
4. Die .py datei bearbeiten telegram web öffnen in die gruppe reingehen dann kopiert den link bsp. https://web.telegram.org/k/#-3406247538
   hinzufügt vor der letzten zahl noch eine 100 also https://web.telegram.org/k/#-1003406247538 kopiert die nummer nach dem #
   -Gruppe A hauptgruppe
   -Gruppe B beliebige 2. Gruppe
   -Gruppe C Vip
   Nutzer id herausfinden könnt ihr mit beliebigen bots zb @usinfobot ihr könnt sie dann jeweils hinzufügen je nachdem welche rolle die jeweilige person kriegt
   bearbeite Zeile 82-84 nach jeweiligen Gruppennamen ihr könnt nach bedarf auch Zeile 99-101 damit könnt ihr festlegen wieviele einladungen man brauch um ein einladungslink für die jeweilige gruppe brauch
   es kann auch festgelegt werden wieviele leaves jemand brauch auf seinem link damit er gekickt wird
  
5. Der bot verfügt auch eine google authenticator funktion bei der falls der admin gebannt wird kann er wieder auf alle gruppen zugreifen und admin bei der jeweiligen um das einzurichten gibt in einer cmd ein

pip install pyotp
und 
py -c "import pyotp; print(pyotp.random_base32())

   hinzufügt den code den euch cmd gibt in der google authenticator app ein und schreibt ihn kurz auf damit ihr ihn griffbereit hab
5. also los gehts erstellt eine public repo mit der Procfile datei, requirments.txt und eure fertige .py für die railway.com seite
  erstellt ein neues project, rechtsklick und github repo setzt eine Variable 1. "BOT_TOKEN" für euren bot token und "TOTP_SECRET" das ist euer Google authenticator Schlüssel ohne "" 
  sagt dem agent create a volume named "data.json" mountpath: /app/storage/ ohne ""
  jetzt ist alles startklar schreibt dem agent deploy all und schaut in den logs wenn du alles richtig gemacht hast wird der bot nicht crashen 
