## Simple Chat app to chat with Ollama Model

This is a simple chat application that allows you to interact with an Ollama model running locally.

- The app features a chat interface.
- It sends your messages to the Ollama API endpoint (http://localhost:11434 by default).
- It displays the responses from the Ollama model.

## Technologies Used

- **Next.js**: A React framework for building server-side rendered and statically generated web applications.
- **React**: A JavaScript library for building user interfaces.
- **TypeScript**: A typed superset of JavaScript that compiles to plain JavaScript.
- **Tailwind CSS**: A utility-first CSS framework for rapidly building custom designs.

## Setup and Running

1.  **Install dependencies**:
    Open your terminal, navigate to the project directory, and run:
    ```bash
    npm install
    ```
    or if you are using Yarn:
    ```bash
    yarn install
    ```

2.  **Run the development server**:
    After the installation is complete, start the development server:
    ```bash
    npm run dev
    ```
    or if you are using Yarn:
    ```bash
    yarn dev
    ```

3.  **Open the application**:
    Open your web browser and go to `http://localhost:3000` (or the port shown in your terminal) to see the application.

Ensure you have an Ollama instance running and accessible at `http://localhost:11434` for the application to connect to.
