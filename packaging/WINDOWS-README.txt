hsmpace for Windows
====================

No Python installation or administrator access is required.

Start the application
---------------------

1. Extract the entire hsmpace-windows ZIP file to a local folder.
   Do not run it inside the ZIP and do not copy hsmpace.exe away from the
   files and folders beside it.
2. Double-click hsmpace.exe and leave its console window open.
3. Open http://127.0.0.1:8731 in a web browser.
4. Close the console window (or press Ctrl+C in it) to stop hsmpace.

The application listens only on this computer. It does not require an
internet connection after the ZIP has been downloaded.

If port 8731 is already in use
------------------------------

Open Command Prompt in the extracted folder and run:

    hsmpace.exe --port 8732

Then open http://127.0.0.1:8732 in a browser.

Windows security prompt
-----------------------

The executable is not code-signed, so Windows may show a SmartScreen warning.
Only choose "More info" then "Run anyway" when the ZIP came from the
hsmpace-windows artifact in the company's trusted GitHub repository.
