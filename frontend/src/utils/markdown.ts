/**
 * Markdown mínimo e seguro para a saída do LLM (texto NÃO confiável):
 * escapa todo HTML primeiro e só depois aplica negrito, itálico, código,
 * títulos e listas. Sem links nem imagens remotas.
 */
const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;')

function inline(s: string): string {
  return s
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<i>$2</i>')
}

export function renderMarkdown(src: string): string {
  const out: string[] = []
  let list: 'ul' | 'ol' | null = null
  const close = () => { if (list) { out.push(`</${list}>`); list = null } }
  for (const raw of esc(src).split('\n')) {
    const line = raw.trimEnd()
    const ul = line.match(/^\s*[-*•]\s+(.*)$/)
    const ol = line.match(/^\s*\d+[.)]\s+(.*)$/)
    const h = line.match(/^#{1,4}\s+(.*)$/)
    if (ul || ol) {
      const kind = ul ? 'ul' : 'ol'
      if (list !== kind) { close(); out.push(`<${kind}>`); list = kind }
      out.push(`<li>${inline((ul ?? ol)![1])}</li>`)
    } else if (h) { close(); out.push(`<h4>${inline(h[1])}</h4>`) }
    else if (!line.trim()) { close() }
    else { close(); out.push(`<p>${inline(line)}</p>`) }
  }
  close()
  return out.join('')
}
