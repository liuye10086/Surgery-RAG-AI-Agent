import DOMPurify from 'dompurify'

/**
 * Strip dangerous HTML tags and event handler attributes from a string.
 * Returns sanitized HTML safe for v-html rendering.
 */
export function sanitizeHtml(html: string): string {
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ['style', 'form', 'input', 'button', 'textarea', 'select'],
    FORBID_ATTR: ['style'],
  })
}
