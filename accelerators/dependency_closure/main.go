// An optional portable closure accelerator. It never decides probe reuse.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"runtime"
	"sort"
	"sync"
)

type Relation struct {
	ID           string   `json:"id"`
	Type         string   `json:"type"`
	Participants []string `json:"participants"`
}
type Input struct {
	Schema    string     `json:"schema"`
	ModelHash string     `json:"reference_model_hash"`
	Relations []Relation `json:"relations"`
	Sources   []string   `json:"sources"`
}
type Slice struct {
	Nodes     []string `json:"nodes"`
	Relations []string `json:"relations"`
}

func closure(relations []Relation, source string) Slice {
	selected, edges := map[string]bool{source: true}, map[string]bool{}
	for _, relation := range relations {
		if relation.ID == source {
			selected = map[string]bool{}
			for _, member := range relation.Participants {
				selected[member] = true
			}
			edges[source] = true
			break
		}
	}
	changed := true
	for changed {
		changed = false
		for _, relation := range relations {
			hit := false
			switch relation.Type {
			case "attached_to", "shared_time_budget", "may_short_circuit":
				for _, member := range relation.Participants {
					if selected[member] {
						hit = true
						break
					}
				}
			case "references", "inherits_overrides":
				hit = selected[relation.Participants[0]]
			case "precedes":
				hit = selected[relation.Participants[1]]
			}
			if hit {
				edges[relation.ID] = true
				for _, member := range relation.Participants {
					if !selected[member] {
						selected[member] = true
						changed = true
					}
				}
			}
		}
	}
	result := Slice{Nodes: []string{}, Relations: []string{}}
	for node := range selected {
		result.Nodes = append(result.Nodes, node)
	}
	for edge := range edges {
		result.Relations = append(result.Relations, edge)
	}
	sort.Strings(result.Nodes)
	sort.Strings(result.Relations)
	return result
}

func run() error {
	workers := flag.Int("workers", 2, "bounded calculation workers")
	flag.Parse()
	if *workers < 1 || *workers > 32 {
		return fmt.Errorf("workers must be in 1..32")
	}
	var input Input
	if err := json.NewDecoder(os.Stdin).Decode(&input); err != nil {
		return err
	}
	if input.Schema != "configpilot.closure-input/1" || input.ModelHash == "" {
		return fmt.Errorf("invalid input contract")
	}
	seen := map[string]bool{}
	for _, relation := range input.Relations {
		if relation.ID == "" || seen[relation.ID] || len(relation.Participants) == 0 ||
			(relation.Type == "precedes" && len(relation.Participants) < 2) {
			return fmt.Errorf("invalid relation")
		}
		seen[relation.ID] = true
	}
	seen = map[string]bool{}
	for _, source := range input.Sources {
		if source == "" || seen[source] {
			return fmt.Errorf("invalid source")
		}
		seen[source] = true
	}
	procs := *workers
	if procs > runtime.NumCPU() {
		procs = runtime.NumCPU()
	}
	runtime.GOMAXPROCS(procs)
	results := make([]Slice, len(input.Sources))
	jobs := make(chan int)
	var group sync.WaitGroup
	for i := 0; i < *workers; i++ {
		group.Add(1)
		go func() {
			defer group.Done()
			for index := range jobs {
				results[index] = closure(input.Relations, input.Sources[index])
			}
		}()
	}
	for i := range input.Sources {
		jobs <- i
	}
	close(jobs)
	group.Wait()
	table := map[string]Slice{}
	for i, source := range input.Sources {
		table[source] = results[i]
	}
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetEscapeHTML(false)
	return encoder.Encode(map[string]any{"schema": "configpilot.closure-output/1",
		"reference_model_hash": input.ModelHash, "slices": table})
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
