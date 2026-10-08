// Build-time compiler for the maintainer-owned Starlark workflow.
package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"runtime/debug"
	"time"

	"go.starlark.net/starlark"
)

func value(v starlark.Value) (any, error) {
	switch x := v.(type) {
	case starlark.String:
		return string(x), nil
	case starlark.Int:
		n, ok := x.Int64()
		if !ok {
			return nil, fmt.Errorf("integer too large")
		}
		return n, nil
	case starlark.Bool:
		return bool(x), nil
	case starlark.NoneType:
		return nil, nil
	case *starlark.List:
		out := []any{}
		for i := 0; i < x.Len(); i++ {
			item, e := value(x.Index(i))
			if e != nil {
				return nil, e
			}
			out = append(out, item)
		}
		return out, nil
	case *starlark.Dict:
		out := map[string]any{}
		for _, pair := range x.Items() {
			key, ok := starlark.AsString(pair[0])
			if !ok {
				return nil, fmt.Errorf("dictionary keys must be strings")
			}
			item, e := value(pair[1])
			if e != nil {
				return nil, e
			}
			out[key] = item
		}
		return out, nil
	default:
		return nil, fmt.Errorf("unsupported workflow value: %s", v.Type())
	}
}

func compile(path string) (map[string]any, error) {
	source, e := os.ReadFile(path)
	if e != nil {
		return nil, e
	}
	if len(source) > 65536 {
		return nil, fmt.Errorf("workflow source exceeds 64KB")
	}
	thread := &starlark.Thread{Name: "workflow", Print: func(_ *starlark.Thread, s string) { fmt.Fprintln(os.Stderr, s) }}
	thread.SetMaxExecutionSteps(100000)
	timer := time.AfterFunc(2*time.Second, func() { thread.Cancel("compilation deadline exceeded") })
	defer timer.Stop()
	globals, e := starlark.ExecFile(thread, path, source, nil)
	if e != nil {
		return nil, e
	}
	workflow, ok := globals["workflow"]
	if !ok {
		return nil, fmt.Errorf("workflow global is required")
	}
	raw, e := value(workflow)
	if e != nil {
		return nil, e
	}
	result, ok := raw.(map[string]any)
	if !ok {
		return nil, fmt.Errorf("workflow must be a dictionary")
	}
	hash := sha256.Sum256(source)
	result["source_sha256"] = hex.EncodeToString(hash[:])
	return result, nil
}

func main() {
	debug.SetMemoryLimit(64 << 20)
	if len(os.Args) != 2 {
		fmt.Fprintln(os.Stderr, "usage: workflow-compiler PATH.star")
		os.Exit(2)
	}
	result, e := compile(os.Args[1])
	if e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetIndent("", "  ")
	if e = encoder.Encode(result); e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
}
