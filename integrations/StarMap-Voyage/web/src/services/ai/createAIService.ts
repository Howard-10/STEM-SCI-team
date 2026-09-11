import type { AIProvider } from './provider'

export function createAIService(provider: AIProvider): AIProvider {
  return Object.freeze({
    generateOverview: provider.generateOverview.bind(provider),
    analyzePaper: provider.analyzePaper.bind(provider),
    comparePapers: provider.comparePapers.bind(provider),
    analyzeExperiment: provider.analyzeExperiment.bind(provider),
    generateWriting: provider.generateWriting.bind(provider),
    analyzeReproduction: provider.analyzeReproduction.bind(provider),
  })
}
