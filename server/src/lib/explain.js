export function explainHeuristically({ issue, difficultyLevel, files, modules }) {
  const lead = files[0] || 'the relevant module'
  const guidance = difficultyLevel === 'Beginner'
    ? 'add a focused regression test before submitting your change'
    : 'cross-check the change against existing tests and any similar merged pull requests before opening yours'
  const scope = modules[0] || 'a single module'
  const second = files[1] ? ` and ${files[1]}` : ''
  return `This issue is a reasonable ${difficultyLevel.toLowerCase()} contribution because it stays within ${scope}. Start by reading ${lead}${second}, then ${guidance}.`
}

export async function explainWithAI({ issue, difficultyLevel, files, modules }) {
  const apiKey = process.env.ANTHROPIC_API_KEY
  if (!apiKey) return null

  const model = process.env.ANTHROPIC_MODEL || 'claude-haiku-4-5-20251001'
  const prompt = [
    'You are helping a new open-source contributor understand a GitHub issue.',
    `Title: ${issue.title}`,
    `Body: ${(issue.body || 'No description provided.').slice(0, 800)}`,
    `Estimated difficulty: ${difficultyLevel}`,
    `Likely affected files: ${files.join(', ') || 'unknown'}`,
    `Likely modules: ${modules.join(', ') || 'unknown'}`,
    '',
    `In 2-3 sentences, explain why this is a good ${difficultyLevel.toLowerCase()} contribution and what the contributor should look at first. Be concrete and concise.`
  ].join('\n')

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 8_000)
  try {
    const response = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      signal: controller.signal,
      headers: {
        'content-type': 'application/json',
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01'
      },
      body: JSON.stringify({
        model,
        max_tokens: 220,
        messages: [{ role: 'user', content: prompt }]
      })
    })
    if (!response.ok) throw new Error(`Anthropic API error ${response.status}`)
    const data = await response.json()
    const text = (data.content || []).map((block) => block.text || '').join(' ').trim()
    return text || null
  } finally {
    clearTimeout(timer)
  }
}
