export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api${path}`, {
      ...options,
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', ...options.headers },
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError(
      0,
      'The local server is unavailable. Start Invisible Work Detector and try again.',
    )
  }
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    if (response.status === 401 && path !== '/session')
      window.dispatchEvent(new Event('iwd:disconnected'))
    const detail = data?.detail
    const message =
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((item: { msg?: string }) => item.msg ?? 'Invalid input').join(' ')
          : 'The request could not be completed. Please try again.'
    throw new ApiError(response.status, message)
  }
  return data as T
}

export const post = <T>(path: string, body: unknown = {}) =>
  api<T>(path, { method: 'POST', body: JSON.stringify(body) })
export const put = <T>(path: string, body: unknown) =>
  api<T>(path, { method: 'PUT', body: JSON.stringify(body) })
export const remove = <T>(path: string, body: unknown = {}) =>
  api<T>(path, { method: 'DELETE', body: JSON.stringify(body) })
