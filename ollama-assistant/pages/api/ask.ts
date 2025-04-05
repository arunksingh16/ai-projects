// pages/api/ask.ts

import type { NextApiRequest, NextApiResponse } from 'next'
import axios from 'axios'

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'POST') return res.status(405).end()

  const { prompt } = req.body

  try {
    const response = await axios.post(
      'http://localhost:11434/api/generate',
      {
        model: 'mistral', // or granite, llama2, etc.
        prompt,
        stream: false,
      },
      {
        headers: {
          'Content-Type': 'application/json',
        },
      }
    )

    res.status(200).json({ response: response.data.response })
  } catch (err) {
    console.error(err)
    res.status(500).json({ error: 'Failed to connect to Ollama' })
  }
}
