import {
  createPublicClient,
  createWalletClient,
  http,
  parseAbiParameters,
  parseAbi,
  parseAbiItem,
  encodeAbiParameters,
  decodeAbiParameters,
  getAddress,
  zeroAddress,
  type Address,
  type Hex,
} from "viem";
import { privateKeyToAccount } from "viem/accounts";
import { PublicKey } from "eciesjs";
export const DKMS = "0x000000000000000000000000000000000000081b" as const;
export const REQUEST_ABI = parseAbiParameters(
  "address,address,address[],bytes[],uint256,bytes[],bytes,address,uint256,uint8",
);
export const RESPONSE_ABI = parseAbiParameters("address,bytes");
export const JOB_ADDED = parseAbiItem(
  "event JobAdded(address indexed executor,bytes32 indexed jobId,address indexed precompileAddress,uint256 commitBlock,bytes precompileInput,address callerAddress,address txOrigin,bytes32 previousBlockHash,uint256 previousBlockNumber,uint256 previousBlockTimestamp,uint256 ttl,uint256 createdAt)",
);
export function encodeDerivation(
  executor: Address,
  owner: Address,
  index: bigint,
) {
  if (
    executor === zeroAddress ||
    owner === zeroAddress ||
    index < 0n ||
    index > 0xffffffffffffffffn
  )
    throw new Error("invalid executor, owner or uint64 key index");
  return encodeAbiParameters(REQUEST_ABI, [
    executor,
    owner,
    [],
    [],
    100n,
    [],
    "0x",
    owner,
    index,
    1,
  ]);
}
export function decodeDerivation(output: Hex) {
  const [paymentAddress, daPublicKey] = decodeAbiParameters(
    RESPONSE_ABI,
    output,
  );
  if (
    paymentAddress === zeroAddress ||
    !/^0x04[0-9a-fA-F]{128}$/.test(daPublicKey)
  )
    throw new Error("invalid DKMS response");
  PublicKey.fromHex(daPublicKey.slice(2), "secp256k1");
  // Payment and DA keys use different derivation domains: do not derive paymentAddress from daPublicKey.
  return { paymentAddress, daPublicKey };
}
export async function waitDerivation(
  client: any,
  tracker: Address,
  hash: Hex,
  fromBlock: bigint,
  timeoutMs = 180000,
) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const logs = await client.getLogs({
      address: tracker,
      event: JOB_ADDED,
      args: { jobId: hash, precompileAddress: DKMS },
      fromBlock,
      toBlock: "latest",
    });
    const hashes = [
      hash,
      ...logs
        .filter((l: any) => l.args.jobId?.toLowerCase() === hash.toLowerCase())
        .map((l: any) => l.transactionHash),
    ];
    for (const candidate of new Set(hashes)) {
      const receipt = await client.request({
        method: "eth_getTransactionReceipt",
        params: [candidate],
      });
      if (!receipt) continue;
      if (receipt.status !== "0x1")
        throw new Error("DKMS transaction reverted");
      const calls = (receipt.spcCalls ?? []).filter(
        (c: any) => c.address?.toLowerCase() === DKMS,
      );
      if (calls.length === 1 && calls[0].output && calls[0].output !== "0x")
        return decodeDerivation(calls[0].output);
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(
    `No settled DKMS result for ${hash}; reconcile before resubmitting`,
  );
}
if (import.meta.main) {
  const required = (name: string) => {
    const value = process.env[name];
    if (!value || value.includes("<")) throw new Error(`Set ${name}`);
    return value;
  };
  const rpc = required("RPC_URL"),
    chainId = Number(required("EXPECTED_CHAIN_ID"));
  const account = privateKeyToAccount(required("PRIVATE_KEY") as Hex);
  const client = createPublicClient({ transport: http(rpc) }),
    wallet = createWalletClient({ account, transport: http(rpc) });
  if ((await client.getChainId()) !== chainId)
    throw new Error("unexpected chain");
  const ritualWallet = getAddress(required("RITUAL_WALLET")),
    tracker = getAddress(required("ASYNC_JOB_TRACKER")),
    executor = getAddress(required("EXECUTOR_ADDRESS"));
  for (const address of [ritualWallet, tracker])
    if (
      !(await client.getCode({ address })) ||
      (await client.getCode({ address })) === "0x"
    )
      throw new Error("missing deployment contract");
  const abi = parseAbi([
    "function availableBalance(address) view returns(uint256)",
    "function deposit() payable",
  ]);
  const deposit = BigInt(process.env.DEPOSIT_WEI ?? "0");
  if (deposit > 0n) {
    const tx = await wallet.writeContract({
      address: ritualWallet,
      abi,
      functionName: "deposit",
      value: deposit,
      chain: null,
    });
    const receipt = await client.waitForTransactionReceipt({ hash: tx });
    if (receipt.status !== "success") throw new Error("deposit failed");
  }
  const available = await client.readContract({
    address: ritualWallet,
    abi,
    functionName: "availableBalance",
    args: [account.address],
  });
  if (available === 0n)
    throw new Error("Fund RitualWallet first or set an explicit DEPOSIT_WEI");
  const fromBlock = await client.getBlockNumber(),
    index = BigInt(process.env.KEY_INDEX ?? "1");
  const hash = await wallet.sendTransaction({
    to: DKMS,
    data: encodeDerivation(executor, account.address, index),
    gas: 1000000n,
    chain: null,
  });
  console.log("ORIGIN_TX_HASH=" + hash);
  const result = await waitDerivation(client, tracker, hash, fromBlock);
  console.log(JSON.stringify(result));
}
