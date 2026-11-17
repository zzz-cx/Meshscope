package main

import (
	"reflect"
	"testing"
)

func TestDirectionalClosure(t *testing.T) {
	relations := []Relation{
		{ID: "early", Type: "precedes", Participants: []string{"first", "later"}},
		{ID: "attach", Type: "attached_to", Participants: []string{"policy", "later"}},
		{ID: "ref", Type: "references", Participants: []string{"policy", "service"}},
		{ID: "unrelated", Type: "references", Participants: []string{"other", "service"}},
	}
	want := Slice{Nodes: []string{"first", "later", "policy", "service"}, Relations: []string{"attach", "early", "ref"}}
	if got := closure(relations, "policy"); !reflect.DeepEqual(got, want) {
		t.Fatalf("got %#v; want %#v", got, want)
	}
	if got := closure(relations, "service"); !reflect.DeepEqual(got.Nodes, []string{"service"}) {
		t.Fatal("reverse reference was followed")
	}
	if got := closure(relations, "first"); !reflect.DeepEqual(got.Nodes, []string{"first"}) {
		t.Fatal("later rule entered predecessor closure")
	}
}

func TestCyclesRelationSourceAndUnknown(t *testing.T) {
	relations := []Relation{
		{ID: "a", Type: "inherits_overrides", Participants: []string{"p", "q"}},
		{ID: "b", Type: "references", Participants: []string{"q", "p"}},
		{ID: "ignored", Type: "unknown", Participants: []string{"p", "z"}},
	}
	want := Slice{Nodes: []string{"p", "q"}, Relations: []string{"a", "b"}}
	if got := closure(relations, "a"); !reflect.DeepEqual(got, want) {
		t.Fatalf("got %#v; want %#v", got, want)
	}
	if got := closure(nil, "absent"); len(got.Nodes) != 1 || len(got.Relations) != 0 {
		t.Fatal(got)
	}
}
