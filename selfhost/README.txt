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

The site creates two more things as it is used. DO NOT DELETE THESE:

    state.json              every week, every setting - the actual data
    uploads\                each week's original spreadsheet, saved as .xlsx


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

Copying state.json and the uploads folder does the same job.


ENCRYPTION (https)
------------------
The site runs on plain http, so browsers show "Not secure". That is only
about encryption in transit - the site works normally.

https is deliberately switched off: it needs port 443 open as well, and it
silently breaks everything if that port is closed. It will not turn itself
back on even if certificate files appear in the folder.


CHANGING HOW SCORING WORKS
--------------------------
Do it on the website itself, under "Scoring weights". Changes save for
everyone immediately.

The scoring rules are also baked into index.html when it is built. If the
project's config.toml is edited on the PC where this was built, rebuild
with "python webapp/build.py" and copy the new index.html over.
