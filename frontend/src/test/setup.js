import '@testing-library/jest-dom/vitest'
import { afterEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'

// jsdom implements no layout, so scrollIntoView is missing. Every real
// browser provides it; stubbing here keeps the gap out of application code.
Element.prototype.scrollIntoView = vi.fn()

afterEach(() => {
  cleanup()
  localStorage.clear()
  vi.clearAllMocks()
})
