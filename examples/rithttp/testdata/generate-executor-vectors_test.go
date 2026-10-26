package rithttp

// Copy into the pinned executor's internal/rithttp directory; run only
// TestExportConsumerVectors with RITHTTP_VECTOR_OUTPUT set to an absolute file.
// Uses that revision's existing memoryStreamStorage and recordingStreamPublisher.
import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	"github.com/ethereum/go-ethereum/crypto"
	storagepkg "github.com/ritual-net/ritual-go-common/storage"
	"github.com/stretchr/testify/require"
)

func TestExportConsumerVectors(t *testing.T) {
	output := os.Getenv("RITHTTP_VECTOR_OUTPUT")
	if output == "" {
		t.Skip("set RITHTTP_VECTOR_OUTPUT to export fixtures")
	}
	key, err := crypto.HexToECDSA(strings.Repeat("0", 63) + "1")
	require.NoError(t, err)
	job := "0x" + strings.Repeat("11", 32)
	fixtures := []map[string]any{}
	var failureResult []byte
	var inputRequest []byte
	for _, sse := range []bool{false, true} {
		for _, mask := range []int{0, 6, 7} {
			recipient := func(i int) []byte {
				if mask&(1<<i) != 0 {
					return crypto.FromECDSAPub(&key.PublicKey)
				}
				return nil
			}
			e := Envelope{JSONTemplate: []byte(`{"hello":true}`), InputRefs: []InputRef{}, Outputs: []OutputPipe{
				{Kind: PipeContract, JQ: `fromjson? | if .usage != null then {id: .id, usage: .usage} else empty end`, Encoding: EncodingJSON, RecipientPublicKey: recipient(0)},
				{Kind: PipeStream, JQ: `fromjson? | if .text != null then .text else empty end`, Encoding: EncodingUTF8, RecipientPublicKey: recipient(1)},
				{Kind: PipeDA, JQ: `fromjson? | if .text != null then .text else empty end`, Encoding: EncodingUTF8, RecipientPublicKey: recipient(2), Destination: storagepkg.StorageRef{Platform: "gcs", Path: "answer.bin", KeyRef: "storage:gcs"}},
			}}
			if sse {
				e.Options = OptionAwaitResponse | OptionStreamResponse
			}
			req, err := Encode(e)
			require.NoError(t, err)
			withInput := e
			withInput.InputRefs = []InputRef{{Ref: storagepkg.StorageRef{Platform: "gcs", Path: "request.json", KeyRef: "storage:gcs"}, SHA256: sha256.Sum256([]byte(`[]`))}}
			withInput.JSONTemplate = []byte(`{"messages":{"$ritual_da":0}}`)
			inputRequest, err = Encode(withInput)
			require.NoError(t, err)
			store := &memoryStreamStorage{uri: "gs://fixture/answer.bin"}
			prepared := &PreparedOutputs{clients: map[int]storagepkg.Client{2: store}}
			publisher := &recordingStreamPublisher{}
			var result []byte
			if sse {
				server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
					w.Header().Set("Content-Type", "text/event-stream")
					_, _ = fmt.Fprint(w, "data: {\"text\":\"Hi\"}\n\ndata: {\"text\":\"!\"}\n\ndata: {\"id\":\"gen-fixture\",\"usage\":{\"cost\":0.0002924}}\n\ndata: [DONE]\n\n")
				}))
				result, err = ExecuteSSE(context.Background(), server.Client(), publisher, StreamRequest{JobHash: job, URL: server.URL, Method: "POST", Body: []byte(`{}`), Envelope: &e, PreparedOutputs: prepared})
				server.Close()
			} else {
				result, err = e.ProcessResponse(context.Background(), 200, []byte(`{"text":"Hi!","id":"gen-fixture","usage":{"cost":0.0002924}}`), prepared, job, publisher)
			}
			require.NoError(t, err)
			outer, err := DecodeResult(result)
			require.NoError(t, err)
			require.False(t, outer.HasError)
			pipes, err := DecodePipeResults(outer.ContractOutput)
			require.NoError(t, err)
			for _, p := range pipes {
				require.True(t, p.Success)
			}
			stored := append([]byte(nil), store.uploaded...)
			if sse && mask == 6 {
				failing := &recordingStreamPublisher{rejectAt: 1}
				run, runErr := newOutputRun(context.Background(), &e, prepared, job, failing)
				require.NoError(t, runErr)
				for _, event := range []string{`{"text":"Hi"}`, `{"text":"!"}`, `{"id":"gen-fixture","usage":{"cost":0.0002924}}`} {
					require.NoError(t, run.consume([]byte(event)))
				}
				failureResult, err = run.finish(200)
				require.NoError(t, err)
			}
			fixtures = append(fixtures, map[string]any{"sse": sse, "encryptionMask": mask, "requestHex": "0x" + hex.EncodeToString(req), "resultHex": "0x" + hex.EncodeToString(result), "framesBase64": publisher.tokens, "daBytes": stored})
		}
	}
	data, err := json.MarshalIndent(map[string]any{"executorCommit": "75c04e3423933887aec74ceea378ce214f01f95c", "commonCommit": "ed73a3f765d8f3762013b32cb8b373d9009fb204", "jobId": job, "privateKey": "0x" + strings.Repeat("0", 63) + "1", "publicKey": "0x" + hex.EncodeToString(crypto.FromECDSAPub(&key.PublicKey)), "cases": fixtures, "publicationFailureResultHex": "0x" + hex.EncodeToString(failureResult), "inputRequestHex": "0x" + hex.EncodeToString(inputRequest)}, "", "  ")
	require.NoError(t, err)
	require.NoError(t, os.WriteFile(output, append(data, '\n'), 0600))
}
