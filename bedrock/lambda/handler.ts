import { BedrockRuntimeClient, InvokeModelCommand } from "@aws-sdk/client-bedrock-runtime";

const client = new BedrockRuntimeClient({ 
    region: process.env.REGION || "eu-west-1" // Use environment variable with fallback
});

exports.handler = async (event: any) => {
    try {
        const body = JSON.parse(event.body || "{}");
        const prompt = body.prompt || "Hello from Bedrock!";

        const inputBody = {
            inputText: prompt,
            textGenerationConfig: {
                maxTokenCount: 4096, // max tokens to generate
                stopSequences: [], // stop sequences for text generation
                temperature: 0, // temperature for randomness
                topP: 1 // nucleus sampling
            }
        };

        const command = new InvokeModelCommand({
            modelId: "amazon.titan-text-lite-v1",
            contentType: "application/json",
            accept: "application/json",
            body: JSON.stringify(inputBody)
        });

        const response = await client.send(command);
        const responseBody = await response.body.transformToString();

        return {
            statusCode: 200,
            headers: { "Content-Type": "application/json" },
            body: responseBody
        };
    } catch (err: any) {
        console.error("Error invoking Bedrock model:", err);
        return {
            statusCode: 500,
            body: JSON.stringify({ error: err.message || "Unknown error" })
        };
    }
};
