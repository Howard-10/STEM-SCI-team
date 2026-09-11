import cors from 'cors'
import dotenv from 'dotenv'
import express, { type NextFunction, type Request, type Response } from 'express'
import { aiRouter } from './routes/ai.js'
import { sendErrorResponse } from './utils/errors.js'

dotenv.config()

const app = express()
const port = Number(process.env.PORT || 3001)
const corsOrigin = process.env.CORS_ORIGIN?.trim() || 'http://127.0.0.1:5178'

app.use(
  cors({
    origin: corsOrigin,
  }),
)
app.use(express.json())

app.use((error: unknown, _request: Request, response: Response, next: NextFunction) => {
  if (error instanceof SyntaxError && 'body' in error) {
    response.status(400).json({
      error: 'validation_error',
      message: '请求体必须是合法 JSON',
    })
    return
  }

  if (error) {
    sendErrorResponse(response, error)
    return
  }

  next()
})

app.get('/health', (_request, response) => {
  response.json({ ok: true })
})

app.use('/api/ai', aiRouter)

app.listen(port, () => {
  console.log(`ResearchPilot server listening on http://localhost:${port}`)
})
