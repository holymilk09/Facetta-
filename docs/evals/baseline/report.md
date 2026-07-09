# Engine evaluation — baseline

Same specs, same instructions, scored identically. Spec conformance = vision read of the output compared against the validated record (species, metal, counts, carat, size). Edit fidelity = intended change applied × rest held static.

## Summary

| engine | render avg | edit avg | runs |
|---|---|---|---|
| grok_direct | 75.6 | 80.0 | 8 |
| flux | 66.8 | None | 5 |
| flux_kontext | None | 100.0 | 3 |

## Every run

| item | engine | kind | score | detail |
|---|---|---|---|---|
| ruby_sunburst_ring | grok_direct | render | 59.3 | {'species_named': 1.0, 'metal_matched': 0.0, 'stone_count': 0.778, 'centre_carat': 0.033, 'centre_size': 0.912} |
| ruby_sunburst_ring | flux | render | 60.2 | {'species_named': 1.0, 'metal_matched': 0.0, 'stone_count': 0.467, 'centre_carat': 0.542, 'centre_size': 0.887} |
| marquise_drop_earring | grok_direct | render | 79.5 | {'species_named': 1.0, 'metal_matched': 1.0, 'stone_count': 0.739, 'centre_carat': 0.349, 'centre_size': 0.726} |
| marquise_drop_earring | flux | render | 77.6 | {'species_named': 1.0, 'metal_matched': 1.0, 'stone_count': 0.739, 'centre_carat': 0.313, 'centre_size': 0.655} |
| aurora_pendant | grok_direct | render | 78.3 | {'species_named': 1.0, 'metal_matched': 1.0, 'stone_count': 0.286, 'centre_carat': 0.676, 'centre_size': 0.875} |
| aurora_pendant | flux | render | 71.7 | {'species_named': 1.0, 'metal_matched': 1.0, 'stone_count': 0.0, 'centre_carat': 0.699, 'centre_size': 0.812} |
| leaf_spray_brooch | grok_direct | render | 74.6 | {'species_named': 1.0, 'metal_matched': 1.0, 'stone_count': 0.227, 'centre_carat': 0.567, 'centre_size': 0.828} |
| leaf_spray_brooch | flux | render | 68.3 | {'species_named': 1.0, 'metal_matched': 1.0, 'stone_count': 0.064, 'centre_carat': 0.451, 'centre_size': 0.763} |
| concept_emerald_halo | grok_direct | render | 86.4 | {'species_named': 1.0, 'metal_matched': 1.0, 'stone_count': 0.684, 'centre_carat': 0.685, 'centre_size': 0.873} |
| concept_emerald_halo | flux | render | 56.3 | {'species_named': 1.0, 'metal_matched': 0.0, 'stone_count': 0.579, 'centre_carat': 0.358, 'centre_size': 0.715} |
| edit:replace the ruby with a blue sap | grok_direct | edit | 100.0 | applied=True drift=none |
| edit:replace the ruby with a blue sap | flux_kontext | edit | 100.0 | applied=True drift=none |
| edit:make the band visibly wider and  | grok_direct | edit | 40.0 | applied=False drift=none |
| edit:make the band visibly wider and  | flux_kontext | edit | 100.0 | applied=True drift=none |
| edit:change all the metal to yellow g | grok_direct | edit | 100.0 | applied=True drift=none |
| edit:change all the metal to yellow g | flux_kontext | edit | 100.0 | applied=True drift=none |
