from sat_instance import SATInstance

class DimacsParser:
    @staticmethod
    def parse_cnf_file(filename: str) -> SATInstance:
        sat_instance = None
        try:
            with open(filename, 'r') as f:
                lines = f.readlines()
            
            iterator = iter(lines)
            line = None
            tokens = None
            
            # Skip comments
            while True:
                try:
                    line = next(iterator).strip()
                    if not line: continue
                    tokens = line.split()
                    if tokens[0] != 'c':
                        break
                except StopIteration:
                    break
            
            # Parse problem line
            if not tokens or tokens[0] != 'p':
                raise ValueError("Error: DIMACS file does not have problem line")
            
            if tokens[1] != 'cnf':
                print("Error: DIMACS file format is not cnf")
                return None
                
            num_vars = int(tokens[2])
            num_clauses = int(tokens[3])
            sat_instance = SATInstance(num_vars, num_clauses)
            
            # Parse clauses from the rest of the file
            # We already consumed lines up to the problem line.
            # We need to process the rest of the lines.
            
            clause_lines = list(iterator)
            
            def token_generator():
                for l in clause_lines:
                    l = l.strip()
                    if not l: continue
                    if l.startswith('c'): continue
                    for t in l.split():
                        yield t

            token_stream = token_generator()
            
            current_clause = set()
            for token in token_stream:
                if token == '0':
                    # End of clause
                    if current_clause: # Avoid empty clauses if 0 is standalone or repeated
                        sat_instance.add_clause(current_clause)
                    current_clause = set()
                elif token == '%':
                    # End of file marker
                    break 
                else:
                    literal = int(token)
                    current_clause.add(literal)
                    sat_instance.add_variable(literal)
                    
            return sat_instance

        except FileNotFoundError:
            raise FileNotFoundError(f"Error: DIMACS file is not found {filename}")
        except Exception as e:
            raise e
