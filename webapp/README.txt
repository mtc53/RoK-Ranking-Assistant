KINGDOM WAR ROOM
================

The website that ranks every member of the kingdom from the weekly
spreadsheet export.

These files all live in C:\WarRoom on the server. Nothing else is needed.

    index.html              the website itself
    server.py               the program that serves it
    start.bat               start the site by hand
    install-autostart.bat   make it start on its own at boot  (run as admin)
    open-firewall.bat       open ports 80 and 443             (run as admin)
    check.bat + check.py    tells you what is wrong if it stops working
    README.txt              this file

The site creates these as it is used. DO NOT DELETE THEM:

    state.json              every week, every setting - the actual data
    state.json.bak          the save before the current one
    backups\                the last 10 saves, older ones pruned for you
    uploads\                each week's original spreadsheet, saved as .xlsx
    .secret                 keeps people logged in across a restart


STARTING IT
-----------
Double-click start.bat and leave the black window open. Closing it stops
the site.

Better: right-click install-autostart.bat and Run as administrator. After
that it starts on its own whenever the server boots, with no window to
leave open, and you can log out safely.

    stop it     schtasks /end /tn "Kingdom War Room"
    start it    schtasks /run /tn "Kingdom War Room"
    remove it   schtasks /delete /tn "Kingdom War Room" /f

When it runs in the background, anything it prints goes to server.log.


WHO CAN CHANGE THE RANKINGS
---------------------------
Out of the box, anybody who can open the page can change them. On a
machine the internet can reach, that is not what you want.

To fix it, make a file next to server.py called

    password.txt

with the password on the first line, and restart the site. From then on
everyone can still READ the page - so a link can go round the officers -
but adding a week, renaming one, or touching the weights asks for the
password first. It is remembered on that computer for 30 days.

If even reading should need the password, add an empty file called
private.txt as well.

Wrong passwords are slowed down and, after ten of them, that computer is
locked out for fifteen minutes.

Change the password by editing password.txt and restarting. Delete
.secret at the same time if you want everyone logged out.


TWO PEOPLE EDITING AT ONCE
--------------------------
If two officers have the site open and both save, the second save used to
quietly wipe the first. Now the site notices, tells whoever was second,
and reloads their page with the other person's change already in it. They
redo their own edit on top. Nothing is lost either way.


IF THE SITE WILL NOT LOAD
-------------------------
Double-click check.bat ON THE SERVER. It checks each thing that has to be
true and stops at the first one that is not, in plain English.

The usual answer is a closed port. Two separate firewalls have to allow it:

    1. Windows       right-click open-firewall.bat, Run as administrator
    2. The VPS host  log in to the Solid VPS control panel and allow
                     inbound TCP port 80

Both. Opening only one is the most common reason for a page that loads
forever and then times out.


BACKING IT UP
-------------
On the website, open "Weekly spreadsheets" and click Download backup. That
one file contains every week, every setting and every original spreadsheet.
Keep a copy somewhere off the server.

The server also keeps its own: state.json.bak is the previous save, and
backups\ holds the last ten. Those live on the same machine, so they are
protection against a bad edit, not against losing the machine. The
downloaded backup is the one that protects you from that.

To go back to an earlier save: stop the site, copy the file you want out of
backups\ over state.json, and start it again.


ENCRYPTION (https)
------------------
If there is no certificate in the folder the site runs on plain http and
browsers show "Not secure". That is only about encryption in transit - the
site works normally, and this is the normal setup.

If a certificate IS in the folder, the site serves https on port 443 AND
keeps the ordinary http site running on port 80. That matters: if port 443
turns out to be closed at the VPS firewall, the site is still reachable on
80 instead of appearing to be dead. Certificate renewals are picked up
without a restart.

Once you have checked that https really works from outside, you can send
http visitors across to it by making an empty file called

    redirect-to-https.txt

Do that only after https is confirmed working. Delete it to go back.


WHAT THE SERVER WILL HAND OUT
-----------------------------
Only the page itself and the data API. state.json, the uploads folder, the
backups, server.log, the password file and any certificate key are not
reachable from a browser, however the address is typed.


CHANGING HOW SCORING WORKS
--------------------------
Do it on the website itself, under "Scoring weights". Changes save for
everyone immediately.

The scoring rules are also baked into index.html when it is built. If the
project's config.toml is edited on the PC where this was built, rebuild
with "python webapp/build.py" and copy the new index.html over.
