import { test, expect } from "bun:test";
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import {
  decodeAbiParameters,
  encodeAbiParameters,
  concatHex,
  sliceHex,
  stringToHex,
  hexToBytes,
  sha256,
  type Hex,
} from "viem";
import {
  encodeRitHttp1,
  decodeRitOut1,
  decodePipeResults,
  requestAbi,
  resultAbi,
  EMPTY_REF,
  PIPE,
  ENCODING,
} from "./rithttp";
import {
  verifyCollectedOutput,
  verifyStreamFrames,
} from "./rithttp-private-io";
import vectors from "./testdata/output_pipe_vectors.json";
const base = {
  options: 0,
  jsonTemplate: { hello: true },
  inputRefs: [],
  outputs: [],
};
const utf8 = (data: Uint8Array) => new TextDecoder().decode(data);
const from64 = (v: string) => new Uint8Array(Buffer.from(v, "base64"));
const contract = {
  kind: PIPE.CONTRACT,
  encoding: ENCODING.JSON,
  jq: "fromjson",
  recipientPublicKey: "0x" as Hex,
  destination: EMPTY_REF,
};

test("request rejects obsolete flags, invalid keys, counts and destinations", () => {
  for (const options of [2, 4, 16, -1, 1.5, 2 ** 32])
    expect(() => encodeRitHttp1({ ...base, options })).toThrow();
  for (const outputs of [
    Array(7).fill(contract),
    [{ ...contract, kind: 3 }],
    [{ ...contract, encoding: 2 }],
    [{ ...contract, jq: "" }],
    [{ ...contract, recipientPublicKey: "0x04" as Hex }],
    [{ ...contract, recipientPublicKey: ("0x04" + "00".repeat(64)) as Hex }],
    [
      {
        ...contract,
        destination: { platform: "gcs", path: "x", keyRef: "storage:gcs" },
      },
    ],
    Array(2).fill({ ...contract, kind: PIPE.STREAM }),
    Array(5).fill({
      ...contract,
      kind: PIPE.DA,
      destination: { platform: "gcs", path: "x", keyRef: "storage:gcs" },
    }),
  ])
    expect(() => encodeRitHttp1({ ...base, outputs })).toThrow();
  const input = {
    ref: { platform: "gcs", path: "request.json", keyRef: "storage:gcs" },
    sha256Digest: sha256(new Uint8Array([1])),
  };
  expect(() =>
    encodeRitHttp1({ ...base, inputRefs: Array(9).fill(input) }),
  ).toThrow();
  expect(() =>
    encodeRitHttp1({
      ...base,
      inputRefs: [{ ...input, sha256Digest: ("0x" + "00".repeat(32)) as Hex }],
    }),
  ).toThrow();
  expect(() =>
    encodeRitHttp1({ ...base, jsonTemplate: "x".repeat(11000) }),
  ).toThrow();
});

test("result handles early errors and rejects trailing bytes/oversize", () => {
  expect(() => decodeRitOut1("0x1234")).toThrow();
  const early = concatHex([
    stringToHex("RITOUT1"),
    encodeAbiParameters(resultAbi, [true, 0, 0, "0x", [], "0x4a534f4e"]),
  ]);
  expect(decodeRitOut1(early).slice(0, 4)).toEqual([true, 0, 0, "0x"]);
  expect(() => decodePipeResults("0x")).toThrow();
  expect(() => decodeRitOut1(concatHex([early, "0x00"]))).toThrow();
  expect(() =>
    decodeRitOut1(concatHex([early, ("0x" + "00".repeat(5120)) as Hex])),
  ).toThrow();
});

for (const fixture of vectors.cases)
  test(`executor conformance SSE=${fixture.sse}, encryption mask=${fixture.encryptionMask}`, () => {
    const [options, jsonTemplate, inputRefs, outputs] = decodeAbiParameters(
      requestAbi,
      sliceHex(fixture.requestHex as Hex, 8),
    );
    expect(
      encodeRitHttp1({
        options,
        jsonTemplate: JSON.parse(utf8(hexToBytes(jsonTemplate))),
        inputRefs,
        outputs,
      }),
    ).toBe(fixture.requestHex as Hex);
    const [hasError, status, encoding, data, receipts, error] = decodeRitOut1(
      fixture.resultHex as Hex,
    );
    expect([hasError, status, encoding, receipts.length, error]).toEqual([
      false,
      200,
      4,
      0,
      "0x00000000",
    ]);
    const results = decodePipeResults(data);
    expect(results.length).toBe(outputs.length);
    for (const [i, result] of results.entries()) {
      expect([
        result.kind,
        result.encoding,
        result.encrypted,
        result.success,
      ]).toEqual([
        outputs[i].kind,
        outputs[i].encoding,
        outputs[i].recipientPublicKey !== "0x",
        true,
      ]);
      const expected = { ...result, jobId: vectors.jobId as Hex, pipeIndex: i };
      if (i === 0) {
        expect(
          utf8(
            verifyCollectedOutput(
              hexToBytes(result.data),
              expected,
              vectors.privateKey as Hex,
            ),
          ),
        ).toBe('{"id":"gen-fixture","usage":{"cost":0.0002924}}');
        expect(result.itemCount).toBe(1);
      } else if (i === 1) {
        const frames = fixture.framesBase64.map(from64);
        expect(result.itemCount).toBe(fixture.sse ? 2 : 1);
        expect(
          verifyStreamFrames(frames, expected, vectors.privateKey as Hex)
            .map(utf8)
            .join(""),
        ).toBe("Hi!");
        expect(result.sizeBytes).toBe(3n);
        expect(result.data).toBe("0x");
        expect(result.outputURI).toBe("");
      } else {
        expect(result.outputURI).toBe("gs://fixture/answer.bin");
        expect(
          utf8(
            verifyCollectedOutput(
              from64(fixture.daBytes),
              expected,
              vectors.privateKey as Hex,
            ),
          ),
        ).toBe("Hi!");
        expect(result.sha256).not.toBe(results[1].sha256);
        expect(result.data).toBe("0x");
      }
    }
    expect(() => decodePipeResults(concatHex([data, "0x00"]))).toThrow();
  });

test("Solidity agrees byte-for-byte with executor and viem requests/results", () => {
  const dir = mkdtempSync(join(tmpdir(), "ritual-rithttp-"));
  try {
    writeFileSync(
      join(dir, "RITHTTP1.sol"),
      readFileSync(new URL("./RITHTTP1.sol", import.meta.url)),
    );
    writeFileSync(
      join(dir, "foundry.toml"),
      '[profile.default]\nsrc="."\ntest="."\nsolc_version="0.8.30"\n',
    );
    const functions = vectors.cases
      .map((fixture, n) => {
        const [options, template, , outputs] = decodeAbiParameters(
          requestAbi,
          sliceHex(fixture.requestHex as Hex, 8),
        );
        const init = outputs
          .map(
            (p, i) =>
              `p[${i}]=RITHTTP1.OutputPipe(${p.kind},string(hex"${Buffer.from(p.jq).toString("hex")}"),${p.encoding},hex"${p.recipientPublicKey.slice(2)}",RITHTTP1.StorageRef("${p.destination.platform}","${p.destination.path}","${p.destination.keyRef}"));`,
          )
          .join("\n");
        return `function testCodec${n}() public pure {
        RITHTTP1.OutputPipe[] memory p=new RITHTTP1.OutputPipe[](3); ${init}
        bytes memory request=RITHTTP1.encodeRequest(${options},hex"${template.slice(2)}",new RITHTTP1.InputRef[](0),p);
        require(keccak256(request)==keccak256(hex"${fixture.requestHex.slice(2)}"),"request mismatch");
        RITHTTP1.Result memory r=RITHTTP1.decodeResult(hex"${fixture.resultHex.slice(2)}");
        require(!r.hasError&&r.upstreamStatus==200&&r.contractEncoding==4&&r.receipts.length==0);
        RITHTTP1.PipeResult[] memory results=RITHTTP1.decodePipeResults(r.contractOutput);
        require(results.length==3&&results[0].kind==0&&results[1].kind==1&&results[2].kind==2);
        require(results[0].success&&results[1].success&&results[2].success);
        require(results[1].sizeBytes==3&&results[1].itemCount==${fixture.sse ? 2 : 1});
        require(results[0].encrypted==${Boolean(fixture.encryptionMask & 1)}&&results[1].encrypted==${Boolean(fixture.encryptionMask & 2)});
        require(sha256(results[0].data)==results[0].sha256Digest);
      }`;
      })
      .join("\n");
    writeFileSync(
      join(dir, "Codec.t.sol"),
      `pragma solidity ^0.8.28; import "./RITHTTP1.sol"; contract CodecTest {
      function decodeOuter(bytes memory v) external pure { RITHTTP1.decodeResult(v); }
      function decodePipes(bytes memory v) external pure { RITHTTP1.decodePipeResults(v); }
      function testRejectTrailingResultBytes() public {
        bool outerRejected; bool pipesRejected;
        try this.decodeOuter(hex"${vectors.cases[0].resultHex.slice(2)}00") {} catch { outerRejected=true; }
        RITHTTP1.Result memory r=RITHTTP1.decodeResult(hex"${vectors.cases[0].resultHex.slice(2)}");
        try this.decodePipes(bytes.concat(r.contractOutput, hex"00")) {} catch { pipesRejected=true; }
        require(outerRejected&&pipesRejected);
      }
      ${functions}}`,
    );
    const out = spawnSync("forge", ["test", "--root", dir, "-vv"], {
      encoding: "utf8",
    });
    if (out.error) throw out.error;
    console.log(out.stdout);
    if (out.status !== 0) throw new Error(out.stderr + out.stdout);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}, 120000);

// Independently pinned capture: do not silently regenerate to match the consumer codec.
test("executor output capture retains its pinned digest", () => {
  expect(
    sha256(
      new Uint8Array(
        readFileSync(
          new URL("./testdata/output_pipe_vectors.json", import.meta.url),
        ),
      ),
    ),
  ).toBe("0x8f7a83c01f5212de7c8a04f670d2a1789263c5a9a8c2044c076793f4718fcdca");
});

test("failed stream preserves authenticated contract usage and independently collected DA", () => {
  const [hasError, status, encoding, body, receipts] = decodeRitOut1(
    vectors.publicationFailureResultHex as Hex,
  );
  expect([hasError, status, encoding, receipts.length]).toEqual([
    true,
    200,
    4,
    0,
  ]);
  const pipes = decodePipeResults(body);
  expect(pipes.map((p) => p.success)).toEqual([true, false, true]);
  expect(pipes[1].errorCode).toBe("0x48545450"); // HTTP: queue rejects second publication
  expect(utf8(hexToBytes(pipes[0].data))).toBe(
    '{"id":"gen-fixture","usage":{"cost":0.0002924}}',
  );
  expect(pipes[1].itemCount).toBe(1);
  expect(pipes[2].outputURI).toBe("gs://fixture/answer.bin");
});
test("unchanged input refs survive current four-field encoding", () => {
  const [options, template, inputRefs, outputs] = decodeAbiParameters(
    requestAbi,
    sliceHex(vectors.inputRequestHex as Hex, 8),
  );
  expect(inputRefs.length).toBe(1);
  expect(inputRefs[0].sha256Digest).toBe(
    sha256(new TextEncoder().encode("[]")),
  );
  expect(inputRefs[0].ref).toEqual({
    platform: "gcs",
    path: "request.json",
    keyRef: "storage:gcs",
  });
  expect(
    encodeRitHttp1({
      options,
      jsonTemplate: JSON.parse(utf8(hexToBytes(template))),
      inputRefs,
      outputs,
    }),
  ).toBe(vectors.inputRequestHex as Hex);
});
