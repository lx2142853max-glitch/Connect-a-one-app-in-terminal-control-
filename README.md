# Android Linux Terminal Agent

A small Python CLI that lets you chat with an API-powered assistant from a Linux terminal running on Android. It can propose shell commands and run them **only after you approve each exact command**.

This is a separate program—not the Arena assistant connected to this conversation. It cannot control Android apps or the Android UI; it can only run commands available inside the Linux environment where you start it.

## Requirements

- A Linux environment on Android (Pocket Linux Debian is a good place to try it).
- Python 3.10 or newer (`python3 --version`). No Python packages are required.
- Git and internet access from that Linux environment.
- An OpenAI API key. API usage may cost extra; a ChatGPT subscription does not include API usage by default.

## Run it in Pocket Linux (Debian)

After this branch is available on GitHub, run:

```sh
cd ~
git clone --single-branch --branch arena/8d4405ef-connect-a-one-app-in-terminal https://github.com/lx2142853max-glitch/Connect-a-one-app-in-terminal-control-.git
mkdir -p ~/agent-work
cd ~/agent-work
python3 ~/Connect-a-one-app-in-terminal-control-/phone_agent.py
```

If Python or Git is missing, install it with the Debian environment's package manager first. If you already downloaded the repository somewhere else, use that location in place of `~/Connect-a-one-app-in-terminal-control-`.

Read the privacy notice and type `y` to continue. Enter your API key at the hidden prompt. The script does not save the key or chat history to a file.

Ask a question in Hindi or English. If the assistant proposes a command, inspect it carefully. Type `y` to run that exact command; pressing Enter refuses it. Use `/clear` to clear the in-memory conversation or `/exit` to quit.

You can change the default model by setting `OPENAI_MODEL` before starting the program, for example:

```sh
export OPENAI_MODEL=gpt-4.1-mini
python3 ~/Connect-a-one-app-in-terminal-control-/phone_agent.py
```

## Important safety and privacy notes

- Chat messages and output from approved commands are sent to the OpenAI API so the assistant can respond. Do not use it with passwords, API keys, private files, or other sensitive output.
- API usage can be billed separately from ChatGPT. Check your provider's pricing and usage limits.
- This is **not a security sandbox**. Commands run with the permissions of the Linux environment and may affect files accessible there. Start it from a test folder, review every command, and do not approve commands you do not understand. Do not run it with elevated permissions for routine tasks.
- The program does not open a remote shell or connect this phone to the current Arena chat.
