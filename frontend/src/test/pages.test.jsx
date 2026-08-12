import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as authApi from '../api/auth'
import * as contentApi from '../api/content'
import * as developerApi from '../api/developer'
import * as documentsApi from '../api/documents'
import { FAKE_USER, TOKEN_KEY, apiError, renderApp } from './utils'

vi.mock('../api/auth')
vi.mock('../api/content')
vi.mock('../api/developer')
vi.mock('../api/documents')

/** Every test below starts signed in. */
beforeEach(() => {
  localStorage.setItem(TOKEN_KEY, 'stored.jwt.value')
  authApi.getCurrentUser.mockResolvedValue(FAKE_USER)
  documentsApi.getSupportedTypes.mockResolvedValue({
    extensions: ['.txt', '.md', '.csv', '.pdf', '.docx'],
    max_file_size_mb: 10,
    max_extracted_characters: 100000,
    ocr_supported: false,
  })
})

const META = { task_type: 'x', model: 'llama-3.3-70b-versatile', usage: { total_tokens: 42 } }

describe('Dashboard', () => {
  it('shows one card per agent and no invented metrics', async () => {
    renderApp('/dashboard')

    expect(await screen.findByRole('heading', { name: /welcome back/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /open content agent/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /open developer agent/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /manage documents/i })).toBeInTheDocument()

    // No backend supplies usage statistics, so none may be displayed.
    expect(screen.queryByText(/saved hours|productivity score|accuracy/i)).toBeNull()
  })
})

describe('Content Agent', () => {
  it('defaults to generation and shows its real backend fields', async () => {
    renderApp('/content')

    expect(await screen.findByRole('heading', { name: /content agent/i })).toBeInTheDocument()
    expect(screen.getByLabelText(/topic/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/content type/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/^tone/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/^audience/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/length/i)).toBeInTheDocument()
  })

  it('swaps the inputs when the task changes', async () => {
    const user = userEvent.setup()
    renderApp('/content')

    await user.selectOptions(await screen.findByLabelText(/what would you like to do/i), 'summarize')

    expect(screen.getByLabelText(/source text/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/summary type/i)).toBeInTheDocument()
    expect(screen.queryByLabelText(/topic/i)).toBeNull()
  })

  it('shows an empty state before anything is run', async () => {
    renderApp('/content')

    expect(await screen.findByText(/no result yet/i)).toBeInTheDocument()
  })

  it('sends the exact backend field names for generation', async () => {
    const user = userEvent.setup()
    contentApi.generate.mockResolvedValue({ content: 'Generated text.', ...META })

    renderApp('/content')
    await user.type(await screen.findByLabelText(/topic/i), 'AI in education')
    await user.click(screen.getByRole('button', { name: /^generate$/i }))

    expect(await screen.findByText('Generated text.')).toBeInTheDocument()
    expect(contentApi.generate).toHaveBeenCalledWith({
      topic: 'AI in education',
      content_type: 'blog',
      tone: 'professional',
      audience: 'general_audience',
      length: 'medium',
    })
  })

  it('renders extraction results as sections, not raw JSON', async () => {
    const user = userEvent.setup()
    contentApi.extract.mockResolvedValue({
      entities: ['Acme Corp'],
      key_points: ['Widget shipped.'],
      facts: ['Revenue rose 18%.'],
      keywords: ['widget'],
      ...META,
    })

    renderApp('/content')
    await user.selectOptions(await screen.findByLabelText(/what would you like to do/i), 'extract')
    await user.type(screen.getByLabelText(/source text/i), 'Acme Corp shipped Widget 3.')
    await user.click(screen.getByRole('button', { name: /extract information/i }))

    expect(await screen.findByRole('heading', { name: /entities/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /key points/i })).toBeInTheDocument()
    expect(screen.getByText('Acme Corp')).toBeInTheDocument()
    expect(screen.queryByText(/"entities":/)).toBeNull()
  })

  it('maps AI_RATE_LIMITED to a readable message', async () => {
    const user = userEvent.setup()
    contentApi.generate.mockRejectedValue(
      apiError('AI_RATE_LIMITED', 'AI service rate limit reached.', { status: 429 }),
    )

    renderApp('/content')
    await user.type(await screen.findByLabelText(/topic/i), 'Anything')
    await user.click(screen.getByRole('button', { name: /^generate$/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/rate limited/i)
  })

  it('shows a loading state and blocks a second submission', async () => {
    const user = userEvent.setup()
    contentApi.generate.mockReturnValue(new Promise(() => {}))

    renderApp('/content')
    await user.type(await screen.findByLabelText(/topic/i), 'Anything')
    await user.click(screen.getByRole('button', { name: /^generate$/i }))

    expect(screen.getByRole('button', { name: /generating/i })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: /generating/i }))
    expect(contentApi.generate).toHaveBeenCalledTimes(1)
  })

  it('validates required input before calling the API', async () => {
    const user = userEvent.setup()
    renderApp('/content')

    await user.click(await screen.findByRole('button', { name: /^generate$/i }))

    expect(await screen.findByText(/enter a topic/i)).toBeInTheDocument()
    expect(contentApi.generate).not.toHaveBeenCalled()
  })
})

describe('Developer Agent', () => {
  it('offers all seven tasks', async () => {
    renderApp('/developer')

    const select = await screen.findByLabelText(/what would you like to do/i)
    const values = within(select).getAllByRole('option').map((option) => option.value)
    expect(values).toEqual([
      'generate', 'explain', 'review', 'refactor', 'tests', 'debug', 'document',
    ])
  })

  it('shows task-specific inputs', async () => {
    const user = userEvent.setup()
    renderApp('/developer')

    const taskSelect = await screen.findByLabelText(/what would you like to do/i)

    await user.selectOptions(taskSelect, 'review')
    expect(screen.getByRole('group', { name: /focus areas/i })).toBeInTheDocument()

    await user.selectOptions(taskSelect, 'debug')
    expect(screen.getByLabelText(/error message or stack trace/i)).toBeInTheDocument()

    await user.selectOptions(taskSelect, 'document')
    expect(screen.getByLabelText(/documentation type/i)).toBeInTheDocument()

    await user.selectOptions(taskSelect, 'generate')
    expect(screen.getByLabelText(/what should the code do/i)).toBeInTheDocument()
  })

  it('renders review findings with severity and a real line number', async () => {
    const user = userEvent.setup()
    developerApi.reviewCode.mockResolvedValue({
      overall_assessment: 'Needs validation.',
      issues: [
        { severity: 'critical', category: 'security', line: 4, problem: 'Unvalidated input.', recommendation: 'Validate it.' },
      ],
      positive_points: [],
      summary: 'Fix input handling.',
      ...META,
    })

    renderApp('/developer')
    await user.selectOptions(await screen.findByLabelText(/what would you like to do/i), 'review')
    await user.type(screen.getByLabelText(/^code/i), 'def f(): pass')
    await user.click(screen.getByRole('button', { name: /review code/i }))

    expect(await screen.findByText(/unvalidated input/i)).toBeInTheDocument()
    expect(screen.getByText('Critical')).toBeInTheDocument()
    expect(screen.getByText('Line 4')).toBeInTheDocument()
  })

  it('says "Line not specified" rather than inventing a line number', async () => {
    const user = userEvent.setup()
    developerApi.reviewCode.mockResolvedValue({
      issues: [{ severity: 'high', category: 'bugs', line: null, problem: 'A problem.', recommendation: 'Fix it.' }],
      ...META,
    })

    renderApp('/developer')
    await user.selectOptions(await screen.findByLabelText(/what would you like to do/i), 'review')
    await user.type(screen.getByLabelText(/^code/i), 'x = 1')
    await user.click(screen.getByRole('button', { name: /review code/i }))

    expect(await screen.findByText(/line not specified/i)).toBeInTheDocument()
    expect(screen.queryByText(/line 0/i)).toBeNull()
  })

  it('labels generated tests as NOT executed', async () => {
    const user = userEvent.setup()
    developerApi.generateTests.mockResolvedValue({
      framework: 'pytest',
      test_code: 'def test_x(): assert True',
      test_cases: [{ name: 'test_x', category: 'normal', description: 'Checks x.', expected_behavior: 'passes' }],
      coverage_notes: 'Covers the happy path.',
      executed: false,
      disclaimer: 'These tests have not been executed or verified by this system.',
      ...META,
    })

    renderApp('/developer')
    await user.selectOptions(await screen.findByLabelText(/what would you like to do/i), 'tests')
    await user.type(screen.getByLabelText(/^code/i), 'def x(): pass')
    await user.click(screen.getByRole('button', { name: /generate tests/i }))

    expect(await screen.findByText(/generated but not executed/i)).toBeInTheDocument()
    // The backend never claims tests pass, and neither may the UI.
    expect(screen.queryByText(/tests passed|all tests pass/i)).toBeNull()
  })

  it('reports debug confidence honestly without upgrading it', async () => {
    const user = userEvent.setup()
    developerApi.analyseBug.mockResolvedValue({
      problem: 'IndexError on empty list.',
      confidence: 'likely',
      likely_cause: 'No empty check.',
      evidence: ['return items[0]'],
      other_possible_causes: [],
      fix: 'Guard the empty case.',
      fixed_code: 'def f(i):\n    return i[0] if i else None',
      prevention: ['Add a test for empty input.'],
      ...META,
    })

    renderApp('/developer')
    await user.selectOptions(await screen.findByLabelText(/what would you like to do/i), 'debug')
    await user.type(screen.getByLabelText(/^code/i), 'def f(i): return i[0]')
    await user.click(screen.getByRole('button', { name: /debug a problem/i }))

    expect(await screen.findByText('Likely')).toBeInTheDocument()
    expect(screen.getByText(/not proven/i)).toBeInTheDocument()
    expect(screen.queryByText('Confirmed')).toBeNull()
    // Appears as both the alert title and in its body text.
    expect(screen.getAllByText(/not reproduced/i).length).toBeGreaterThan(0)
  })

  it('sends the exact backend field names for explain', async () => {
    const user = userEvent.setup()
    developerApi.explainCode.mockResolvedValue({
      summary: 'It adds numbers.',
      line_by_line_explanation: ['Defines a function.'],
      important_concepts: [],
      potential_issues: [],
      ...META,
    })

    renderApp('/developer')
    await user.type(await screen.findByLabelText(/^code/i), 'def add(a, b): return a + b')
    await user.click(screen.getByRole('button', { name: /explain code/i }))

    expect(await screen.findByText(/it adds numbers/i)).toBeInTheDocument()
    expect(developerApi.explainCode).toHaveBeenCalledWith({
      language: 'python',
      code: 'def add(a, b): return a + b',
    })
  })

  it('surfaces AI_INVALID_OUTPUT readably', async () => {
    const user = userEvent.setup()
    developerApi.explainCode.mockRejectedValue(
      apiError('AI_INVALID_OUTPUT', 'AI returned an unexpected format.', { status: 502 }),
    )

    renderApp('/developer')
    await user.type(await screen.findByLabelText(/^code/i), 'x = 1')
    await user.click(screen.getByRole('button', { name: /explain code/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/invalid result/i)
  })
})

describe('Documents', () => {
  it('shows supported formats fetched from the backend, not hardcoded', async () => {
    renderApp('/documents')

    expect(await screen.findByText(/\.txt, \.md, \.csv, \.pdf, \.docx/i)).toBeInTheDocument()
    expect(screen.getByText(/up to 10 MB/i)).toBeInTheDocument()
    expect(documentsApi.getSupportedTypes).toHaveBeenCalled()
  })

  it('shows an empty state before any upload', async () => {
    renderApp('/documents')

    expect(await screen.findByText(/nothing extracted yet/i)).toBeInTheDocument()
  })

  it('uploads a file and shows the extracted text with metadata', async () => {
    const user = userEvent.setup()
    documentsApi.uploadDocument.mockResolvedValue({
      filename: 'report.pdf',
      extension: '.pdf',
      content_type: 'application/pdf',
      size_bytes: 2048,
      characters: 120,
      text: 'Quarterly report contents.',
      metadata: { page_count: 2, pages_with_text: 2 },
    })

    renderApp('/documents')
    const input = await screen.findByLabelText(/choose a file/i)
    await user.upload(input, new File(['%PDF-1.4'], 'report.pdf', { type: 'application/pdf' }))

    expect(screen.getByText('report.pdf')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /upload and extract/i }))

    expect(await screen.findByText(/quarterly report contents/i)).toBeInTheDocument()
    expect(screen.getByText(/page count: 2/i)).toBeInTheDocument()
  })

  it('rejects an unsupported extension before uploading', async () => {
    // applyAccept: false bypasses the input's `accept` filter, which is the
    // first line of defence. This test covers the second: the explicit check
    // in the change handler, which still matters for drag-and-drop and for
    // pickers that let a user select "All files".
    const user = userEvent.setup({ applyAccept: false })
    renderApp('/documents')

    // Wait for the server's supported types to arrive — the client-side check
    // deliberately does nothing until it knows what the backend accepts.
    await screen.findByText(/\.txt, \.md, \.csv, \.pdf, \.docx/i)

    const input = screen.getByLabelText(/choose a file/i)
    await user.upload(input, new File(['print(1)'], 'script.py', { type: 'text/x-python' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/not supported/i)
    expect(documentsApi.uploadDocument).not.toHaveBeenCalled()
  })

  it('maps DOCUMENT_TEXT_NOT_FOUND to a readable message', async () => {
    const user = userEvent.setup()
    documentsApi.uploadDocument.mockRejectedValue(
      apiError('DOCUMENT_TEXT_NOT_FOUND', 'No readable text was found.', { status: 422 }),
    )

    renderApp('/documents')
    const input = await screen.findByLabelText(/choose a file/i)
    await user.upload(input, new File(['%PDF'], 'scan.pdf', { type: 'application/pdf' }))
    await user.click(screen.getByRole('button', { name: /upload and extract/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/no readable text/i)
  })

  it('hands extracted text to the Content Agent without a backend call', async () => {
    const user = userEvent.setup()
    documentsApi.uploadDocument.mockResolvedValue({
      filename: 'notes.txt',
      extension: '.txt',
      content_type: 'text/plain',
      size_bytes: 30,
      characters: 26,
      text: 'Some extracted document text.',
      metadata: { encoding: 'utf-8' },
    })

    renderApp('/documents')
    const input = await screen.findByLabelText(/choose a file/i)
    await user.upload(input, new File(['hello'], 'notes.txt', { type: 'text/plain' }))
    await user.click(screen.getByRole('button', { name: /upload and extract/i }))
    await screen.findByRole('button', { name: /use in content agent/i })
    await user.click(screen.getByRole('button', { name: /use in content agent/i }))

    // Landed on the Content Agent with the text pre-filled.
    expect(await screen.findByRole('heading', { name: /content agent/i })).toBeInTheDocument()
    expect(screen.getByLabelText(/source text/i)).toHaveValue('Some extracted document text.')
  })
})
