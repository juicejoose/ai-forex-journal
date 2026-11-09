// Hosted builds use the same authenticated origin as the page.
export const API = import.meta.env.DEV ? 'http://127.0.0.1:8000' : '/api'
