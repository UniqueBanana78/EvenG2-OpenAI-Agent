# EvenG2-OpenAI-Agent
Middleman between Even G2 Smart Glasses Agent and OpenAI API.

A Python server application that listens for Even AI agent messages, passes them on to the OpenAI API, and sends responses to the glasses - it achieves near-realtime responses when used with non-reasoning models.

Chat to your Even G2 Smart Glasses as if you were chatting to ChatGPT!!

Bypasses the need for OpenClaw etc.

**What you need:**

Windows PC or server (Windows because on this version I gave it a System Tray icon so I can (a) see it's running, (b) view the log and (c) exit it cleanly - to run on other platforms you will need to edit the code to remove reliance on Windows elements);

Ability to port forward a public IP on your internet connection to the same port on the LAN IP address of your PC running this app, and open any Firewall as necessary;

OpenAI API account with an API key and some credits (NOT a subscription to ChatGPT, this is not the same!).

**What to do:**

Go to the Settings for Even AI in the Even Realities App on your phone. Under "Agent configuration", add a new agent.

Set this new Agent to point to http://mydomain:myport/v1/chat/completions  (where **mydomain** is either your public IP address or domain or dynamic DNS domain for your internet connection, and **myport** is a port of your choice - default is 4567);

Set a Token only you know;

Port forward "myport" in your Router to the same port on the LAN IP of your computer that will be running this Python app.

Rename the example.env.txt file to .env and edit this to insert (1) your Token from above, (2) your API key from Open AI and (3) the port you have chosen. Optionally you can set the maximum message length (default is 400 characters) and which OpenAI model to use (I found that GPT 4.1 gives a good balance of quality vs speed).

Install the necessary Python packages - Run **pip install -r requirements.txt**

Run: **python smartglasses.pyw** - if you configured it correctly, you will see a "Glasses" icon in your system tray. This has the option on right-click to View Log or Quit.

Wearing your Even G2 glasses, say "Hey Even" and ask a question - for example, ask it for the recipe for a Strawberry Sundae and check that you get a valid response. Do not ask the AI questions like "what's the time", as OpenAI doesn't know the current time!

The server application listens for incoming webhooks from the Even Agent, validates the Token, appends the incoming message to the log, with a date/time stamp (removing any duplicates). Then it polls the OpenAI API using your API key. Finally it delivers the reponse to the Even Agent to display on the glasses, and writes the outbound message to a log, with date/time stamp.

If you want to view the console output, rename smartglasses.pyw to smartglasses.py

**What you can define within the smartglasses.pyw file:**

Timeout if there is no response - change **timeout=15** within the code, 15 is a good number as the glasses stop listening for a reply after 30 seconds;

Number of re-tries if no response from API - change **for attempt in range(2)** to another number. The second (and subsequent) tries only happen AFTER the timeout, set above, expires. A good balance might be a timeout of 15 and max re-tries of 2 - you can experiment! Note that the OpenAI API has it's own timeout of 25 seconds - but allowing the full length of this leaves little time for re-tries because the Glasses will stop listening at 30;

Max token usage - change **"max_completion_tokens": 150** if you want longer answers, but keep in mind your MAX_CHARS setting in the .env will still truncate the final text;

Number of messages to store in the thread before discarding - change **MAX_TURNS = 12** to a higher number if you want a longer memory, at the expense of more token use;

Elapsed time (in seconds) since last message before closing the thread - change **SESSION_TTL = 600** if you wish. If you don't speak to the glasses for 600 seconds (10 minutes), the app wipes the conversation history. Next time you speak, it will be a brand new conversation. Change to 3600 to remember context for a full hour, or 120 to reset after just 2 minutes.

**Risks**

Aside from the absence of liability as covered in the MIT licence - this uses Flask web server which is not the most secure environment - Python even warns you not to use Flask on a public server. It also requires you to open a port on your router and port forward it to this app. It doesn't use SSL on the connections between the glasses and the server, so your Token is sent unencrypted, as are the responses (if you have the knowledge, you could change this with a self-hosted SSL certificate and only a small change to the code). The connection from the App to OpenAI is, however, made over https.

**Please use at your own risk!**
