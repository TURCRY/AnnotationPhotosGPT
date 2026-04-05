echo === Activation de l'environnement virtuel ===
cd /d D:\GPT4All_Local\gpt4all_env
call Scripts\activate.bat

echo === Démarrage du serveur Flask (gpt4all_flask_debug.py) ===
cd /d D:\GPT4All_Local\flask_server
python gpt4all_flask_debug.py

pause
