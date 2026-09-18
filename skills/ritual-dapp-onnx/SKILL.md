---
name: ritual-dapp-onnx
description: On-chain ML model inference via the ONNX precompile. Use when building dApps that run machine learning models directly on-chain with synchronous results.
---

# ONNX ML Inference — Ritual dApp Patterns

## Overview

The ONNX precompile (`0x0800`) enables smart contracts to run machine learning models on-chain. ONNX is a **synchronous precompile** — you call it, the node runs the model using its built-in ONNX runtime during block execution, and the result is returned in the same call. No external services, no waiting, no callbacks. `eth_call` works for read-only simulation.

**Precompile address**: `0x0000000000000000000000000000000000000800`
**Execution model**: Synchronous — call returns result directly, can be called multiple times per TX, no deposits or fee locking required
**Use cases**: Classification, regression, anomaly detection, embeddings, scoring — any ML task with a trained ONNX model.

## ABI

```solidity
(bytes mlModelId, bytes tensorData, uint8 inputArithmetic, uint8 inputFixedPointScale,
 uint8 outputArithmetic, uint8 outputFixedPointScale, uint8 rounding)
```

| Field | Type | Description |
|-------|------|-------------|
| mlModelId | bytes | HuggingFace model ID (UTF-8 encoded). See **Model ID** below. |
| tensorData | bytes | RitualTensor-encoded input data |
| inputArithmetic | uint8 | Input number format: 1 = fixed-point, 2 = IEEE 754 float |
| inputFixedPointScale | uint8 | Fixed-point decimal places (ignored if inputArithmetic = 2) |
| outputArithmetic | uint8 | Output number format: 1 = fixed-point, 2 = IEEE 754 float |
| outputFixedPointScale | uint8 | Fixed-point decimal places for output |
| rounding | uint8 | Rounding mode: 1 = half-even (round nearest), 2 = truncate, 3 = floor, 4 = ceil |

## Model ID

Format: `hf/<owner>/<repo>/<file>.onnx@<40-char-commit-hash>`. Public HuggingFace repos only. Branch names (`@main`) are rejected — commit hashes are required so all nodes download identical model bytes. Get the hash via `curl -s https://huggingface.co/api/models/<owner>/<repo> | jq '.sha'`.

This ONNX model ID format is a model locator, not a DA `StorageRef`. For DA storage references and credential formats (`gcs`/`hf`/`pinata`), use `ritual-dapp-da`.

Test model: `hf/Ritual-Net/sample_linreg/linreg_10_features.onnx@fd0501654c4144a9900a670c5c9a074b6bd3d4ef` (10 float inputs → 1 float output).

**First-time model download (JIT):** Nodes cache models locally. When a block builder encounters a transaction referencing an uncached model, three things happen: (1) a background download from HuggingFace is triggered, (2) the transaction is skipped for the current block but stays in the mempool, and (3) the transaction is automatically retried in subsequent blocks until the download completes (typically 1-5 blocks). `eth_call` follows the same code path — it triggers the download but returns `PrecompileError` until the model is cached.

## RitualTensor Encoding

Input and output tensors use the RitualTensor format:

```solidity
struct RitualTensor {
    uint8 dtype;      // Data type
    uint16[] shape;   // Tensor dimensions
    int32[] values;   // Flattened values
}
```

**Data types:**

| dtype | Type | Solidity array type | Notes |
|-------|------|---------------------|-------|
| 1 | BOOL | `bool[]` | Boolean values |
| 4 | FLOAT16 | `int16[]` | IEEE 754 half-precision bit-patterns |
| 5 | FLOAT32 | `int32[]` | IEEE 754 bit-patterns cast to int32 |
| 6 | FLOAT64 | `int64[]` | IEEE 754 double-precision bit-patterns |
| 9 | INT8 | `int8[]` | Raw int8 values |
| 10 | INT16 | `int16[]` | Raw int16 values |
| 11 | INT32 | `int32[]` | Raw int32 values |
| 12 | INT64 | `int64[]` | Raw int64 values |
| 13 | UINT8 | `uint8[]` | Raw uint8 values |
| 14 | UINT16 | `uint16[]` | Raw uint16 values |
| 15 | UINT32 | `uint32[]` | Raw uint32 values |
| 16 | UINT64 | `uint64[]` | Raw uint64 values |

> **Most common:** dtype=5 (FLOAT32) for ML models. The `int32[]` values array contains IEEE 754 bit patterns reinterpreted as signed integers.

**Encoding FLOAT32 values:** Each float is converted to its IEEE 754 binary representation and stored as an int32. In TypeScript:

```typescript
function floatToInt32(f: number): number {
  const buf = new ArrayBuffer(4);
  new Float32Array(buf)[0] = f;
  return new Int32Array(buf)[0];
}

function int32ToFloat(i: number): number {
  const buf = new ArrayBuffer(4);
  new Int32Array(buf)[0] = i;
  return new Float32Array(buf)[0];
}
```

## TypeScript: Encoding an ONNX Request

```typescript
import { encodeAbiParameters, bytesToHex } from 'viem';

const ONNX_PRECOMPILE = '0x0000000000000000000000000000000000000800';

function encodeRitualTensor(dtype: number, shape: number[], values: number[]): `0x${string}` {
  return encodeAbiParameters(
    [{ type: 'uint8' }, { type: 'uint16[]' }, { type: 'int32[]' }],
    [dtype, shape, values]
  );
}

function encodeOnnxRequest(
  modelId: string,
  tensorData: `0x${string}`,
  opts?: { inputArithmetic?: number; outputArithmetic?: number; rounding?: number }
): `0x${string}` {
  return encodeAbiParameters(
    [
      { type: 'bytes' },   // mlModelId
      { type: 'bytes' },   // tensorData
      { type: 'uint8' },   // inputArithmetic
      { type: 'uint8' },   // inputFixedPointScale
      { type: 'uint8' },   // outputArithmetic
      { type: 'uint8' },   // outputFixedPointScale
      { type: 'uint8' },   // rounding
    ],
    [
      bytesToHex(new TextEncoder().encode(modelId)),
      tensorData,
      opts?.inputArithmetic ?? 2,  // 2 = IEEE 754 float
      0,                            // not used for float
      opts?.outputArithmetic ?? 2,  // 2 = IEEE 754 float
      0,                            // not used for float
      opts?.rounding ?? 1,          // 1 = half-even (round nearest)
    ]
  );
}

// Example: run a 10-feature linear regression model
const inputValues = [0.5, -0.14, 0.65, 1.52, -0.23, -0.23, 1.58, 0.77, -0.47, 0.54].map(floatToInt32);
const tensorData = encodeRitualTensor(5, [1, 10], inputValues); // FLOAT32, shape [1, 10]
const encoded = encodeOnnxRequest(
  'hf/Ritual-Net/sample_linreg/linreg_10_features.onnx@fd0501654c4144a9900a670c5c9a074b6bd3d4ef',
  tensorData
);
```

## Solidity: Consumer Contract

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract ONNXConsumer {
    address constant ONNX = 0x0000000000000000000000000000000000000800;

    event InferenceResult(bytes32 indexed requestId, bytes output);

    function classify(
        bytes calldata modelId,
        bytes calldata tensorData
    ) external returns (bytes memory) {
        bytes memory input = abi.encode(
            modelId,
            tensorData,
            uint8(2),  // inputArithmetic: 2 = IEEE 754
            uint8(0),  // inputFixedPointScale: N/A for IEEE 754
            uint8(2),  // outputArithmetic: 2 = IEEE 754
            uint8(0),  // outputFixedPointScale: N/A for IEEE 754
            uint8(1)   // rounding: 1 = half-even (round nearest)
        );

        (bool ok, bytes memory result) = ONNX.call(input);
        require(ok, "ONNX inference failed");

        bytes32 requestId = keccak256(abi.encodePacked(msg.sender, block.number, modelId));
        emit InferenceResult(requestId, result);

        return result;
    }
}
```

## Decoding the Output

The precompile output is wrapped: `(bytes tensorEncoded, uint8 outputArithmetic, uint8 outputScale, uint8 rounding)`. The inner `tensorEncoded` is a RitualTensor: `(uint8 dtype, uint16[] shape, int32[] values)`.

```typescript
import { decodeAbiParameters } from 'viem';

// Step 1: Unwrap the outer response envelope
function decodeOnnxResponse(result: `0x${string}`): {
  tensorData: `0x${string}`;
  outputArithmetic: number;
  outputScale: number;
  rounding: number;
} {
  const [tensorData, outputArithmetic, outputScale, rounding] = decodeAbiParameters(
    [{ type: 'bytes' }, { type: 'uint8' }, { type: 'uint8' }, { type: 'uint8' }],
    result
  );
  return { tensorData: tensorData as `0x${string}`, outputArithmetic, outputScale, rounding };
}

// Step 2: Decode the inner RitualTensor
function decodeTensor(tensorData: `0x${string}`): { dtype: number; shape: number[]; values: number[] } {
  const [dtype, shape, values] = decodeAbiParameters(
    [{ type: 'uint8' }, { type: 'uint16[]' }, { type: 'int32[]' }],
    tensorData
  );
  return { dtype, shape: [...shape], values: [...values] };
}

// Full decode with float conversion
function decodeFloatOutput(result: `0x${string}`): number[] {
  const { tensorData } = decodeOnnxResponse(result);
  const { dtype, values } = decodeTensor(tensorData);
  if (dtype !== 5) return values.map(Number);
  return values.map(v => int32ToFloat(Number(v)));
}
```

## When to Use ONNX

Use ONNX when you have a trained ONNX model and need structured input/output (tensors, vectors, scores). Input is numeric, output is numeric, and the result is deterministic — the same model with the same input always produces the same output across all nodes.
