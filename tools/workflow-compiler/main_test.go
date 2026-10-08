package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestCompiler(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "flow.star")
	os.WriteFile(path, []byte(`workflow = {"nodes": [str(x) for x in range(3)], "version": 1}`), 0600)
	data, e := compile(path)
	if e != nil {
		t.Fatal(e)
	}
	if data["source_sha256"] == "" {
		t.Fatal("missing hash")
	}
	os.WriteFile(path, []byte(`load("os", "system")`), 0600)
	if _, e = compile(path); e == nil {
		t.Fatal("load must not access host modules")
	}
	os.WriteFile(path, []byte(`workflow = {"nodes": [x for x in range(10000000)]}`), 0600)
	if _, e = compile(path); e == nil {
		t.Fatal("unbounded work must fail")
	}
}
