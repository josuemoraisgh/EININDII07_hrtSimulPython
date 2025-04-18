from react.repeatFunction import RepeatFunction
from PySide6.QtCore import QObject, Slot
from react.react_var import ReactVar
import control as ctrl
import numpy as np
import json
import ast


class SimulTf(QObject):
    
    dictDB = {}
    systems = {}
    states = {}
    delay = {} 
      
    def __init__(self, stepTime):
        super().__init__()
        self.stepTime = stepTime  # em milisegundos
        # Inicializa a função repetida para rodar a simulação de forma contínua
        self._repeated_function = RepeatFunction(self._simulation_step, stepTime)     

    @Slot()
    def tfConnect(self, data: ReactVar,  isConnect: bool):
        if isConnect == True:
            self.dictDB[(data.tableName, data.rowName, data.colName)] = data
            num_str, den_str, delay_str, _ = data.getTFunc().split(",")
            num = ast.literal_eval(num_str.replace(" ", ","))
            den = ast.literal_eval(den_str.replace(" ", ","))

            self.delay[(data.tableName, data.rowName, data.colName)] = float(delay_str)
            if self.delay[(data.tableName, data.rowName, data.colName)] != 0.0:
                G = ctrl.TransferFunction(num, den)
                # Aproximação de Padé para o atraso de self.delay segundos (ordem 1)
                num_delay, den_delay = ctrl.pade(self.delay[(data.tableName, data.rowName, data.colName)], 1)  # atraso = self.delay (seg), ordem = 1
                # Função de transferência do atraso
                delay_tf = ctrl.TransferFunction(num_delay, den_delay)
                # Sistema completo com atraso
                sys_tf = G * delay_tf
            else:
                sys_tf = ctrl.TransferFunction(num, den)
            sys_ss = ctrl.tf2ss(sys_tf)
            sysd = ctrl.c2d(sys_ss, self.stepTime / 1000.0, method='tustin')

            self.systems[(data.tableName, data.rowName, data.colName)] = {
                "A": np.array(sysd.A),
                "B": np.array(sysd.B),
                "C": np.array(sysd.C),
                "D": np.array(sysd.D)
            } 
            self.states[(data.tableName, data.rowName, data.colName)] = np.zeros((sysd.A.shape[0], 1))          
        else:
            self.dictDB.pop((data.tableName, data.rowName, data.colName), None)
            self.delay.pop((data.tableName, data.rowName, data.colName), None)
            self.systems.pop((data.tableName, data.rowName, data.colName), None)
            self.states.pop((data.tableName, data.rowName, data.colName), None)
            
    def start(self, state: bool):
        """Inicia a execução da simulação."""
        if state:
            self.load_states()             
            self._repeated_function.start()
        else:
            self._repeated_function.stop()
            self.save_states()            

    def reset(self):
        """Finaliza a execução e reseta os estados."""      
        self._repeated_function.stop() 
        for key in self.states:
            self.states[key] = np.zeros_like(self.states[key])

    def _simulation_step(self):
        """Calcula o próximo passo para todas as funções de transferência."""
        for key, system in self.systems.items():
            input_Value = self.dictDB[key].inputValue

            # Calcula a saída com o estado atual
            output = system["C"].dot(self.states[key]) + system["D"] * input_Value
            # Atualiza o estado
            self.states[key] = system["A"].dot(self.states[key]) + system["B"] * input_Value

            # Armazena a saída e emite sinal
            self.dictDB[key]._value =  np.clip(float(output), 0.0001, 1.0)
            self.dictDB[key].valueChangedSignal.emit(self.dictDB[key])
    
    def save_states(self):
        for key, state in self.states.items():
            try:
                state_json = json.dumps(state.tolist())
                self.dictDB[key].reactDB.storage.setData("TFSTATES", "|".join(key[:-1]), key[-1], state_json)
            except Exception as e:
                print(f"Erro ao salvar estado de {key}: {e}")

    def load_states(self):
        try:
            key = list(self.dictDB.keys())[0]
            for row in self.dictDB[key].reactDB.storage.rowKeys("TFSTATES"):
                for col in self.dictDB[key].reactDB.storage.colKeys("TFSTATES"):
                    key = tuple(row.split("|")) + (col,)
                    if key in self.systems:
                        state_str = self.dictDB[key].reactDB.storage.getRawData("TFSTATES", row, col)
                        if state_str:
                            try:
                                self.states[key] = np.array(json.loads(state_str))
                            except Exception as e:
                                print(f"❌ Erro ao carregar estado de {key}: {e}")
                    else:
                        self.dictDB[key].reactDB.storage.setData("TFSTATES", row, col, None)
        except Exception as e:
            print(f"❌ Erro geral ao carregar estados do banco: {e}")

    def clean_orphan_states(self):
        """Remove do banco os TFSTATES que não têm sistema correspondente"""
        try:
            for row in self.dictDB[key].reactDB.rowKeys("TFSTATES"):
                for col in self.dictDB[key].reactDB.colKeys("TFSTATES"):
                    key = tuple(row.split("|")) + (col,)
                    if key not in self.systems:
                        self.dictDB[key].reactDB.setData("TFSTATES", row, col, None)
        except Exception as e:
            print(f"Erro ao limpar estados órfãos: {e}")