import type {
  AnalyzeExperimentInput,
  AnalyzeExperimentResult,
  AnalyzePaperInput,
  AnalyzePaperResult,
  AnalyzeReproductionInput,
  AnalyzeReproductionResult,
  ComparePapersInput,
  ComparePapersResult,
  GenerateOverviewInput,
  GenerateOverviewResult,
  GenerateWritingInput,
  GenerateWritingResult,
} from './types'

export interface AIProvider {
  generateOverview(input: GenerateOverviewInput): Promise<GenerateOverviewResult>
  analyzePaper(input: AnalyzePaperInput): Promise<AnalyzePaperResult>
  comparePapers(input: ComparePapersInput): Promise<ComparePapersResult>
  analyzeExperiment(input: AnalyzeExperimentInput): Promise<AnalyzeExperimentResult>
  generateWriting(input: GenerateWritingInput): Promise<GenerateWritingResult>
  analyzeReproduction(input: AnalyzeReproductionInput): Promise<AnalyzeReproductionResult>
}
