// 只从标准输入读取图片，在本机 Vision 中识别；标准输出仅返回文字与定位。
import Foundation
import Vision
import ImageIO

func fail() -> Never {
    FileHandle.standardError.write(Data("本地文字识别未完成。".utf8))
    exit(2)
}
let input = FileHandle.standardInput.readDataToEndOfFile()
guard input.count <= 80 * 1024 * 1024,
      let source = CGImageSourceCreateWithData(input as CFData, nil),
      let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else { fail() }
do {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = false
    let supported = try request.supportedRecognitionLanguages()
    let languages = ["zh-Hans", "zh-Hant", "en-US"].filter { supported.contains($0) }
    request.recognitionLanguages = languages
    try VNImageRequestHandler(cgImage: image, options: [:]).perform([request])
    var lines: [[String: Any]] = []
    for observation in request.results ?? [] {
        guard let candidate = observation.topCandidates(1).first else { continue }
        let text = candidate.string
        var characters: [[String: Any]] = []
        for index in text.indices {
            let next = text.index(after: index)
            let range = index..<next
            let rect = (try? candidate.boundingBox(for: range))?.boundingBox ?? observation.boundingBox
            characters.append(["text": String(text[range]), "box": [rect.minX, 1 - rect.maxY, rect.maxX, 1 - rect.minY]])
        }
        lines.append(["text": text, "confidence": candidate.confidence, "chars": characters])
    }
    let result: [String: Any] = ["lines": lines, "languages": languages]
    let output = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
    FileHandle.standardOutput.write(output)
} catch { fail() }
