# logfire-demo

This project demonstrates [Pydantic Logfire](https://pydantic.dev/logfire).

It's designed to be a simple app with enough functionality to show some of the things Logfire can do.

## Running the demo

1. Follow [these](https://docs.pydantic.dev/logfire/guides/first_steps/) instructions to get setup with logfire, you'll want to export your logfire write token as `LOGFIRE_TOKEN` so it can be used by docker compose.
2. Create a GitHub token and set the `GITHUB_TOKEN` environment variable. `export GITHUB_TOKEN=<github token from step 4>`  (this is used for the "GitHub lines of code counter" demo).
3. Create an OpenAI token and set the `OPENAI_API_KEY` environment variable (this is used for the "LLM Query" demo)
4. Run `make up`.

Now you can go to the [Logfire demo page](http://localhost:8000/) and try the app.

You can find your project `Dashboard` link at the end of the page. Click on the dashboard link
to see the live logs from the demo project.
