# PerfLens Case Study — Findings

No confirmed findings yet.

## Finding Template

### FINDING-XXX

**Phase:**  
**Feature:**  
**Test ID:**  

**Expected behavior:**  

**Actual behavior:**  

**Reproduction:**  

**Evidence:**  

**Investigation:**  

**Root cause:**  

**Impact:**  

**Severity:**  

**Workaround:**  

**Potential improvement:**  

**Retest result:**  

### FINDING-CASE-001

**Phase:** Case Study Construction  
**Feature:** Initial CMake build  
**Test ID:** BUILD-002  

**Expected behavior:**  
Case-study executable should compile and link successfully.

**Actual behavior:**  
Compilation succeeded, but linking failed with undefined references to `sin` and `sqrt`.

**Reproduction:**
```bash
cmake -S . -B build -DENABLE_OPENMP=ON -DENABLE_MPI=OFF
cmake --build build -j4
